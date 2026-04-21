# Phase 13 — Agent Auto-Managed Portfolio (서비스화 뼈대)

> **Status**: SKELETON DESIGN ONLY. 구현은 user 승인 후 시작.
> **Goal**: 엔진(agent) 이 자동으로 portfolio를 운영하고, 그 기록을 frontend로 노출하여 구독자(human user)들이 follow-only 할 수 있는 구조.
> **Differs from Phase 12**: Phase 12 는 USER 가 본인 broker 거래 입력. Phase 13 은 AGENT 가 자동 paper-trade 하고 그 기록 = canonical source of truth.

---

## 0. Product Vision

```
[r1000 엔진]
    ↓
[Agent가 매월 paper-trade] (자동)
    ↓
[정석 포트] — Free tier
    ├── 18개 종목 + agent_entry_date / agent_avg_cost / unrealized_return
    └── frontend: 구독자들이 본인 broker로 따라 매수
    
[성장주 포트] — Paid tier (concentrated, N=5)
    ├── 5개 종목 + 동일 enrichment
    └── frontend: 유료 구독자 전용

[USER override] — 선택적
    └── manual_positions.yaml: 구독자가 본인 broker 정보 입력하면 PERSONAL view 추가됨
```

**핵심 차이**:
- Phase 12 (manual_positions.yaml) → user 거래 입력 채널 (sticks 운영)
- Phase 13 (agent ledger) → engine 자체 paper trading 기록 (canonical)
- 둘 다 공존: agent_* 컬럼 (frontend 표준) + manual_* 컬럼 (user의 actual)

---

## 1. Architecture

### 1.1 Two Independent Portfolios

| Portfolio | File | Tier | Holdings count | Rebalance |
|---|---|---|---|---|
| **정석 (Standard / main diversified)** | `portfolio_latest.csv` | FREE | 18 names | Monthly |
| **성장주 (Concentrated / growth)** | `concentrated_portfolio_latest.csv` | PAID | 5 names (N=5/1m/score_power champion) | Monthly |

각각 **독립 ledger** 와 **독립 state** 가짐.

### 1.2 Data flow

```
Pipeline run (run_local.py)
    ↓
generates portfolio_latest.csv + concentrated_portfolio_latest.csv  (engine output)
    ↓
[Phase 13A] auto-track:
    - load prev agent state
    - compute trade diffs
    - append events to ledger
    - recompute new state
    - save state
    ↓
[Phase 13E] enrich CSVs with agent_* columns + write summary JSON
    ↓
Frontend (구독 서비스 UI)
    ├── Free: portfolio_latest.csv + recent_trades.json
    └── Paid: + concentrated_portfolio_latest.csv
```

---

## 2. File Structure

```
G:\내 드라이브\r1000_top30_institutional\
├── manual_positions.yaml               # USER override (Phase 12B, optional)
└── outputs\
    ├── portfolio_latest.csv            # 정석 (free tier source)
    ├── concentrated_portfolio_latest.csv  # 성장주 (paid tier source)
    ├── current_portfolio_summary.json  # frontend-friendly snapshot
    ├── recent_trades.json              # last 30-90 days of agent trades
    └── ops\
        ├── agent_main_portfolio_ledger.parquet       # 정석 event log
        ├── agent_main_portfolio_state.json           # 정석 cumulative state
        ├── agent_concentrated_portfolio_ledger.parquet  # 성장주 event log
        ├── agent_concentrated_portfolio_state.json   # 성장주 cumulative state
        ├── live_portfolio_state.json                 # USER's actual (Phase 12)
        └── live_portfolio_state_history.parquet      # state snapshots
```

---

## 3. Ledger Schema (append-only event log)

`agent_main_portfolio_ledger.parquet`:

| Column | Type | Description |
|---|---|---|
| `event_id` | str (UUID) | Idempotency key (skip if already exists) |
| `timestamp_utc` | datetime | When event was recorded |
| `rebalance_date` | date | Engine's rebal date (event "happened") |
| `ticker` | str | Stock symbol |
| `action` | enum | `INITIAL_BUY` \| `NEW_BUY` \| `ADD` \| `TRIM` \| `EXIT` \| `HOLD` |
| `shares_delta` | float | +/- (positive = buy, negative = sell) |
| `price` | float | Execution price (month-end close at rebalance_date) |
| `weight_before` | float | Position weight before event (0.0 if NEW_BUY) |
| `weight_after` | float | Position weight after event (0.0 if EXIT) |
| `reason` | str | `engine_inception` \| `engine_added` \| `engine_reweight` \| `engine_dropped` \| `engine_thesis_break` |
| `engine_commit_sha` | str | Agent version (audit trail) |
| `notes` | str | Free text |

**Action types**:
- `INITIAL_BUY`: First-ever buy at agent inception (only on first ever ledger write)
- `NEW_BUY`: Added a previously-unheld ticker (engine added it to recommendation)
- `ADD`: Increased existing position (weight up)
- `TRIM`: Decreased existing position (weight down, but still held)
- `EXIT`: Sold all (weight → 0, ticker no longer in portfolio)
- `HOLD`: No change (optional event for completeness, can skip)

---

## 4. Agent State Schema

`agent_main_portfolio_state.json`:

```json
{
  "schema_version": "v1",
  "portfolio_kind": "main",
  "inception_date": "2026-04-21",
  "last_rebalance_date": "2026-04-21",
  "last_synced_utc": "2026-04-21T11:00:00Z",
  "engine_version": "2026-04-20-phase11-multibagger-sleeve",
  "engine_commit_sha": "d63b80e",
  "starting_capital_usd": 100000.0,
  "current_equity_usd": 100000.0,
  "positions": [
    {
      "ticker": "NVDA",
      "shares": 78.81,
      "weight": 0.14,
      "avg_cost": 177.64,         // Weighted-average cost basis
      "current_price": 177.64,    // Latest reference price
      "unrealized_return": 0.0,
      "first_buy_date": "2026-04-21",   // entry_date for display
      "last_trade_date": "2026-04-21",
      "days_held": 0,
      "thesis_status": "active",
      "n_events": 1
    },
    ...
  ],
  "exited_positions_history": [
    // ticker history of exits with realized return
  ]
}
```

**Cost basis method**: **Weighted Average**.
- New BUY: `avg_cost = (old_basis + new_shares*price) / new_total_shares`
- TRIM (partial sell): `avg_cost unchanged`, shares reduced
- EXIT (full sell): position removed, realized return = `(exit_price - avg_cost) / avg_cost` recorded in `exited_positions_history`

---

## 5. Sub-Stages

### Phase 13A — Ledger writer (~2h)

**New module**: `r1000_agent_portfolio.py` (or extend `r1000_portfolio_state.py`)

Functions:
- `compute_trade_events(prev_state: dict, current_portfolio: pd.DataFrame, rebalance_date: str, engine_commit_sha: str) -> list[dict]`
  - Compares prev positions vs new portfolio
  - Generates list of events (NEW_BUY, ADD, TRIM, EXIT)
  - Idempotency: same (rebalance_date, ticker, action) → same event_id
- `append_ledger_events(ledger_path: Path, events: list[dict]) -> int` — returns # appended
- `bootstrap_inception_ledger(portfolio_df, prices, paths) -> int` — first run only

**Decision rule (rebalance detection)**:
- Compare `current_rebalance_date` from `portfolio_latest.csv` with `state.last_rebalance_date`
- If different → real rebalance happened → generate events
- If same → no-op (pipeline re-ran without rebal change)

### Phase 13B — State computer (~2h)

- `compute_agent_state_from_ledger(ledger_df, current_prices) -> dict`
  - Walks events chronologically
  - Maintains running positions with weighted-avg cost basis
  - On EXIT: moves to exited_positions_history
- `save_agent_state(state, paths)` / `load_agent_state(paths)`

**Key functions**:
- `apply_event(state, event) -> state` — single event update (pure function for testability)
- `recompute_unrealized_return(state, current_prices) -> state`

### Phase 13C — Pipeline integration (~1h)

In `r1000_pipeline.py` `export_outputs`:

After portfolio_latest.csv + concentrated_portfolio_latest.csv are written:
```python
# Phase 13C: agent auto-track
from r1000_agent_portfolio import (
    auto_track_agent_portfolio,
)
try:
    main_state = auto_track_agent_portfolio(
        portfolio_kind="main",
        portfolio_csv_path=portfolio_path,
        ledger_path=paths["ops"] / "agent_main_portfolio_ledger.parquet",
        state_path=paths["ops"] / "agent_main_portfolio_state.json",
        engine_commit_sha=ENGINE_COMMIT_SHA,
        rebalance_date=str(latest_dt.date()),
    )
    log(f"[Phase 13C] main portfolio: {main_state['n_positions']} positions, "
        f"{main_state['n_new_events']} new events")
except Exception as exc:
    log(f"[Phase 13C] main agent track failed: {exc}")

# Same for concentrated...
```

### Phase 13D — Concentrated portfolio support (~1.5h)

- Same logic, different files
- Concentrated has `concentrated_top1_latest.csv` for N=1 alternative
- Multiple concentrated tiers possible (N=3, N=5, N=7)
- For MVP: single canonical = N=5/1m/score_power champion

### Phase 13E — Frontend outputs (~1h)

**New columns in `portfolio_latest.csv`**:
```
existing: rank, ticker, Name, sector, weight, score, ...
NEW (from agent state):
  agent_first_buy_date     # entry date
  agent_avg_cost           # cost basis
  agent_current_price      # latest price
  agent_unrealized_return  # (current - cost) / cost
  agent_days_held
  agent_n_events           # # of trades on this position
  agent_thesis_status
NEW (from manual_positions.yaml, if present):
  manual_entry_date        # user's actual buy date
  manual_avg_cost          # user's actual cost
  manual_unrealized_return # user's actual P&L
```

**`current_portfolio_summary.json`** (frontend-consumable):
```json
{
  "tier": "free",
  "portfolio_kind": "main",
  "as_of_utc": "2026-04-21T11:00:00Z",
  "as_of_rebalance_date": "2026-04-21",
  "engine_version": "2026-04-20-phase11-multibagger-sleeve",
  "agent_inception_date": "2026-04-21",
  "agent_lifetime_cagr": 0.2310,
  "agent_lifetime_total_return": 2.853,
  "n_positions": 17,
  "cash_weight": 0.0366,
  "positions": [
    {
      "rank": 1, "ticker": "NVDA", "name": "NVIDIA",
      "weight": 0.14,
      "agent_avg_cost": 177.64,
      "current_price": 177.64,
      "unrealized_return": 0.0,
      "first_buy_date": "2026-04-21",
      "days_held": 0,
      "sector": "Technology"
    }, ...
  ]
}
```

**`recent_trades.json`**:
```json
{
  "as_of_utc": "2026-04-21T11:00:00Z",
  "lookback_days": 90,
  "trades": [
    {
      "rebalance_date": "2026-04-21",
      "ticker": "NVDA",
      "action": "INITIAL_BUY",
      "shares": 78.81,
      "price": 177.64,
      "weight_after": 0.14,
      "reason": "engine_inception"
    }, ...
  ]
}
```

### Phase 13F — Smoke tests + CHANGELOG (~30min)

Tests:
- `test_ledger_idempotency`: same (rebalance_date, ticker) won't double-record
- `test_state_from_ledger`: synthetic ledger → expected state
- `test_avg_cost_weighted`: ADD events compute correct weighted-avg
- `test_exit_realized_return`: EXIT moves to history with correct realized P&L
- `test_concentrated_isolated`: main + concentrated ledgers don't interfere

---

## 6. Critical Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Cost basis method | Weighted average | Simplest, no FIFO/LIFO ambiguity |
| Inception date | Today (first run date) | Honest — can't claim retro paper-trade |
| Rebalance detection | Compare `last_rebalance_date` vs current | Avoid double-trading on pipeline reruns |
| Cash treatment | Tracked as residual (1 - sum(weights)) | Implicit, no separate position |
| Pricing | Month-end close from current_price_live | Matches backtest convention |
| Idempotency key | UUID = hash(rebalance_date + ticker + action) | Deterministic, deduplicatable |
| Concentrated source | N=5/1m/score_power champion | Already optimal per CE v2 grid |
| Manual override priority | manual_positions.yaml (if exists) wins for `manual_*` cols | User-specific PnL view distinct from agent's canonical |
| Lifetime equity | backtest_equity + agent paper trading concat | Already works via Phase 12C; agent state replaces no_live_data path |

---

## 7. Out of Scope (explicit)

These are NOT in Phase 13:
- ❌ **Real broker integration** (Fidelity/IBKR API). User still trades manually based on agent's recommendations.
- ❌ **Push notifications** (frontend service layer responsibility, not engine).
- ❌ **Multiple subscriber accounts** (engine produces 1 canonical agent portfolio, not per-user variants).
- ❌ **Tax lot accounting** (FIFO/LIFO/specific-lot). Weighted-avg only.
- ❌ **Dividend tracking** (cash dividends, special distributions). Future Phase 14.
- ❌ **Currency hedging** (USD only).
- ❌ **Frontend UI itself** — engine produces JSON/CSV; frontend devs build UI.

---

## 8. Total Effort Estimate

| Sub-stage | Hours | Risk |
|---|---|---|
| 13A Ledger writer | 2 | LOW |
| 13B State computer | 2 | LOW |
| 13C Pipeline integration | 1 | LOW |
| 13D Concentrated support | 1.5 | LOW |
| 13E Frontend outputs | 1 | LOW |
| 13F Smoke tests + docs | 0.5 | LOW |
| **TOTAL** | **8h** | LOW (no model changes, all infrastructure) |

---

## 9. Bootstrap Strategy

First-ever pipeline run with Phase 13 enabled:

1. Read `portfolio_latest.csv` → 17 active holdings
2. For each holding: emit `INITIAL_BUY` event with:
   - `rebalance_date` = today
   - `price` = current_price_live
   - `shares` = (weight × $100,000) / price
   - `reason` = "engine_inception"
3. Save to `agent_main_portfolio_ledger.parquet`
4. Compute initial state → save to `agent_main_portfolio_state.json`
5. Same for concentrated (if `concentrated_portfolio_latest.csv` exists)

**$100,000 starting capital** is the canonical unit (matches backtest convention).

---

## 10. Subscription Tier Differentiation (frontend logic, NOT in engine)

For documentation clarity, this is what the frontend would gate:

| Output | Free Tier | Paid Tier |
|---|---|---|
| `portfolio_latest.csv` | ✅ | ✅ |
| `current_portfolio_summary.json` (main) | ✅ | ✅ |
| `recent_trades.json` (main) | ✅ delayed 24h | ✅ real-time |
| `concentrated_portfolio_latest.csv` | ❌ | ✅ |
| `current_portfolio_summary.json` (concentrated) | ❌ | ✅ |
| `lifetime_equity_curve.csv` | ✅ main only | ✅ both |

Engine produces ALL files. Frontend gates by subscription. **Engine doesn't care about subscription state**.

---

## 11. Risks + Open Questions

1. **Rebalance frequency mismatch**: backtest = monthly, but pipeline can be re-run daily. Solution: rebal detection via `last_rebalance_date` field in state.

2. **Engine signal flip-flop**: if engine adds NVDA → drops next month → adds again, ledger has 3 events for NVDA. Reasonable behavior for paper-trading but realized losses accumulate. Solution: nothing special; this is honest reflection.

3. **Adjustment for splits/dividends**: stock splits change per-share price. yfinance Adj Close handles dividends but engine uses raw Close in some places. **Open**: how to record agent's pre-split shares vs post-split? Defer to Phase 14.

4. **Agent inception bias**: starting today means subscribers see CAGR of ~0% for first month. Need patience until live data accumulates. Could backfill 2026-02 to 2026-04 by re-running pipeline at past dates? **Decision**: defer; honest "started today" is cleaner.

5. **Multiple concentrated variants**: if user wants both N=3 and N=5 sleeves, that's 2 paid tiers. Initial Phase 13 = single canonical (N=5/1m/score_power). Future expansion = parameterize.

---

## 12. Acceptance Criteria

Phase 13 ships when:
- [ ] First pipeline run with Phase 13 generates ledger with 17 INITIAL_BUY events
- [ ] Second pipeline run (same rebalance_date) does NOT add duplicate events (idempotency)
- [ ] Pipeline run after engine drops a ticker generates EXIT event with correct realized return
- [ ] `portfolio_latest.csv` has `agent_*` columns populated
- [ ] `current_portfolio_summary.json` is frontend-consumable
- [ ] `recent_trades.json` shows last 90 days
- [ ] Concentrated portfolio gets parallel treatment in separate files
- [ ] Smoke tests 6+ new tests pass
- [ ] CHANGELOG entry documents the new agent-tracking behavior

---

## 13. Migration from Phase 12

- `manual_positions.yaml` (Phase 12B): keep as USER PERSONAL override channel
- portfolio_latest.csv: add `agent_*` columns (canonical) + keep `manual_*` columns (user)
- `lifetime_equity_curve.csv` (Phase 12C): swap data source from manual_positions.yaml to agent_main_portfolio_state.json
- `lifetime_metrics.json`: same swap

Backward compatibility: existing Phase 12 features keep working. Phase 13 adds NEW canonical layer.
