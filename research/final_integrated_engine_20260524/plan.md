# Final Integrated Engine — Implementation Plan

**Date**: 2026-05-24
**Status**: Pre-execution roadmap
**Parent spec**: `CODEX_HANDOFF_PLAN_C_V3_5_20260520.md` (v3.6 addendum §16-§23)
**Companion**: `research.md` (this directory)

## 1. Execution sequence (high-level)

```
Day 1:     Phase C0.1 KILL SWITCH merge (BLOCKING #1)
Day 1-5:   A1/A2 broker accounting fix (parallel, independent)
Day 2-3:   Phase E1 drawdown segment audit (truth-finding, BLOCKING for E design)
Day 2-3:   Phase D1/D5/D7 event builders (parallel)
Day 4-5:   Phase E2 crisis signal builder (after E1)
Day 6:     Merge D1+D5+D7
Day 7-8:   Phase D2 labeler
Day 8-10:  Phase E3+E4 crisis classifier + composite score
Day 9-10:  Phase D3 multi-bucket scoring
Day 11-12: Phase E5+E6 exposure + reentry ladders
Day 13-14: Phase D4 live PDA + Phase F hold-vs-replace (parallel)
Day 15:    Phase E7 governor replay
Day 16-18: Phase G integrated challenger grid
Day 19-21: Stress window validation + first verdict

Month 2-7: 6mo SHIP consecutive verdict wait
Month 7+:  Phase C8/C9 promotion unlock
```

## 2. Phase E (Crisis Governor) — detailed steps

### E1: Drawdown segment audit

**Branch**: `codex/plan-c-e1-dd-segment-audit`
**Effort**: 1-2 days
**Dependency**: None (read-only audit)

**Deliverables**:
- `tools/run_drawdown_segment_report.py`
- `outputs/drawdown_segments/main.csv`
- `outputs/drawdown_segments/concentrated.csv`
- `outputs/drawdown_segments/report.md` (Markdown analysis)

**Schema** (per row = one drawdown event > 10%):
```
peak_date, peak_value,
trough_date, trough_value, drawdown_pct,
first_below_10pct_date, first_below_20pct_date, first_below_30pct_date,
days_peak_to_first_10pct, days_peak_to_trough, days_trough_to_recovery,
cash_weight_at_peak, cash_weight_at_10pct, cash_weight_at_20pct,
cash_weight_at_trough, cash_weight_at_recovery,
position_count_at_peak, position_count_at_trough,
held_winner_count_at_trough, held_broken_count_at_trough,
new_buys_during_dd, sells_during_dd, replacement_swaps_during_dd,
top_3_holdings_at_peak, top_3_holdings_at_trough,
spy_drawdown_same_window, vix_max_in_window,
classified_crisis_type
```

**Acceptance**: Both main + concentrated reports generated; report.md
identifies whether 2022 main DD was from holding losers (replacement gap)
or from late new-buy throttle (signal gap).

### E2: Crisis signal builder

**Branch**: `codex/plan-c-e2-crisis-signals`
**Effort**: 1-2 days
**Dependency**: None (uses existing macro data + price cache)

**Deliverables**:
- `tools/run_crisis_signal_builder.py`
- `outputs/crisis_signals/daily_features.parquet`

**Features** (per trading day, T close):
- Market trend: SPY/QQQ MA20/50/200 status, 5d/10d/20d drawdown
- Volatility: VIX level, 60d z-score, 3-day spike
- Credit: HY OAS bps, IG OAS bps, 60d z-scores
- Rates: 10Y yield, 5d change bps, yield curve inversion flag
- Breadth: % stocks above MA200/MA50, advance-decline slope 20d
- Liquidity: SPY/QQQ dollar volume z-scores
- Portfolio: current drawdown, weighted holdings drawdown

**Acceptance**: Daily features computed for full price cache history; no
look-ahead (verified via `tools/run_pit_audit_for_pda.py`).

### E3: Crisis type classifier

**Branch**: `codex/plan-c-e3-e4-crisis-classify`
**Effort**: 1-2 days
**Dependency**: E2 merged

**Deliverables**:
- `tools/run_crisis_type_classifier.py`
- `outputs/crisis_signals/daily_classification.csv`

**Rule-based classification**:
```python
def classify(features):
    if features["spy_5d_dd"] > 0.08 and features["vix_zscore_60d"] > 2.5:
        return "shock_crash"
    if (features["hy_spread_zscore_60d"] > 2.0
        and features["ig_spread_zscore_60d"] > 1.5):
        return "credit_crisis"
    if (features["spy_below_ma200"] and features["qqq_below_ma200"]
        and features["days_below_ma200"] > 30
        and features["ten_year_5d_change_bps"] > 0):
        return "slow_bear"
    if 0.03 < features["spy_5d_dd"] < 0.08 and 0.5 < features["vix_zscore_60d"] < 2.0:
        return "normal_pullback"
    if (features["vix_zscore_60d"] < 0.5
        and features["spy_above_ma50"]
        and features["advdec_line_slope_20d"] > 0.3):
        return "recovery"
    return "normal"
```

**Validation**: Classifier output for 2020-03-12 must be `shock_crash`, for
2022-06-13 must be `slow_bear`, for 2024-08-05 must be `normal_pullback`.

### E4: Composite crisis_score

**Branch**: same as E3
**Effort**: 0.5 day

**Formula** (clipped to [0, 1] per component):
```python
crisis_score = (
    0.25 * market_trend_breakdown_score    # spy/qqq below MA + 20d_dd
  + 0.20 * credit_stress_score             # HY/IG spread z
  + 0.15 * volatility_spike_score          # VIX level + z
  + 0.15 * breadth_breakdown_score         # pct above MA200
  + 0.10 * liquidity_drain_score           # dollar volume anomaly
  + 0.10 * rate_shock_score                # 10y 5d change
  + 0.05 * portfolio_damage_score          # current DD
)
```

**Validation**: 2020-03-16 crisis_score > 0.75; 2022-10-14 > 0.65;
2024-08-05 < 0.40; 2025-01-15 (steady market) < 0.20.

### E5: Exposure ladder

**Branch**: `codex/plan-c-e5-e6-ladders`
**Effort**: 1-2 days
**Dependency**: E4 merged

**Config** (`r1000_config.py`):
```python
crisis_governor_apply_to_live: bool = False  # default OFF, gated by kill switch
crisis_score_thresholds: list[float] = [0.30, 0.50, 0.70]
crisis_cash_ladder: dict = {
    "normal":  (0.00, 0.05),
    "caution": (0.05, 0.10),
    "defense": (0.10, 0.25),
    "crisis":  (0.25, 0.50),
}
crisis_new_buy_throttle_at: float = 0.30
crisis_concentrated_exposure_floor: float = 0.30
```

**Wiring**: New function `apply_crisis_governor_to_portfolio()` in
`r1000_pipeline.py`, called after position sizing but before final write.

### E6: Re-entry ladder

**Branch**: same as E5
**Effort**: 1 day

**Formula**:
```python
reentry_score = (
    0.30 * vix_normalization
  + 0.25 * qqq_ma_reclaim
  + 0.20 * breadth_thrust
  + 0.15 * credit_spread_stabilization
  + 0.10 * leadership_recovery
)
```

**Rule**: monotonic exposure restoration (reentry_score must rise; partial
reversals on temporary noise blocked by hysteresis).

### E7: Governor replay tool

**Branch**: `codex/plan-c-e7-governor-replay`
**Effort**: 2-3 days
**Dependency**: E1-E6 merged

**Deliverables**:
- `tools/run_cagr_preserving_crisis_governor_replay.py`
- `outputs/crisis_governor_replay/main_with_governor.csv`
- `outputs/crisis_governor_replay/concentrated_with_governor.csv`
- `outputs/crisis_governor_replay/stress_window_metrics.csv`
- `outputs/crisis_governor_replay/false_alarm_log.csv`

**Stress windows**:
- 2020-02-01 to 2020-05-31
- 2021-11-01 to 2022-12-31
- 2024-01-01 to 2024-12-31
- 2025-01-01 to latest

**Acceptance**:
- 2020 concentrated MDD reduces from -38.45% to ≤ -28%
- 2022 main MDD reduces from -33.45% to ≤ -25%
- Normal-zone cash stays ≤ 8%
- Cash trap days ≤ 15 across full backtest
- False alarm count ≤ 5/year

## 3. Phase F (Hold-vs-Replace) — detailed steps

**Branch**: `codex/plan-c-f-hold-vs-replace`
**Effort**: 3-4 days
**Dependency**: Phase D4 merged (replacement pool from Smart Money + Tenbagger)

### F1: Position state classifier

```python
def classify_position(ticker, current_data):
    if (current_data["price"] > entry * 0.95
        and current_data["rs"] > 60
        and not ma200_violation):
        return "winner_intact"
    if -0.15 < drawdown_pct < -0.05:
        return "weakening"
    if drawdown_pct < -0.15 or ma200_violation or rs < 30:
        return "broken"
    if drawdown_pct > 0.30 and pe_zscore > 2.0:
        return "winner_overextended"
    return "neutral"
```

### F2: Replacement candidate selection

Sources (priority order):
1. `outputs/tenbagger_watchlist/latest.csv` (active discovery)
2. `outputs/smart_money/top30_latest.csv` (institutional confirmation)
3. Future winner score top decile

Thresholds:
- Normal market: candidate must beat held by ≥ 0.75σ on selection_score
- Weakening: candidate beat by ≥ 0.35σ
- Crisis: only quality_growth_score > 0.7 candidates

### F3: Safety guards

- Never replace if candidate in same broken sector + industry
- Never reduce concentrated to below `crisis_concentrated_exposure_floor`
- Replacement requires PIT-clean `available_from_ts`
- Max 2 replacements per rebalance to avoid churn

### F4: Output

`outputs/hold_vs_replace/decisions.csv`:
```
ticker, current_state, recommendation,
held_score, candidate_ticker, candidate_score, score_delta_sigma,
replace_reason, risk_off_safety_check_passed
```

## 4. Phase G (Integrated Challenger) — detailed steps

**Branch**: `codex/plan-c-g-integrated-challenger`
**Effort**: 4-5 days
**Dependency**: All of Phase D + E + F merged

### G1: Grid dimensions

```python
GRID = {
    "main_target_n": [12, 15, 18],
    "concentrated_target_n": [2, 3, 5],   # N=7 NEVER
    "evidence_weight_main": [0.05, 0.08, 0.10],
    "evidence_weight_concentrated": [0.10, 0.15, 0.20],
    "crisis_governor": ["off", "conservative", "aggressive"],
    "hold_vs_replace": ["off", "normal", "strict"],
    "smart_money_confirmation_weight": [0.0, 0.05, 0.08],
    "post_disclosure_alpha_weight": [0.0, 0.03, 0.05],
}
# Total: 3*3*3*3*3*3*3*3 = 6561 combinations
# Reduce with smart pruning to ~200-500 viable combos
```

### G2: Per-combo execution

For each combo:
1. Apply config overrides
2. Run broker-ledger next-close replay (existing `tools/run_broker_ledger_replay.py`)
3. Compute CAGR, MDD, Sharpe, turnover, fees, stress window metrics
4. Bootstrap CI on CAGR + MDD
5. Cost sensitivity at 25/50/75/100 bps

### G3: Promotion gates

**Main passes if ALL**:
- ΔCAGR ≥ -0.5pp (preferably positive)
- ΔMDD ≥ +5pp
- 2022 stress MDD improves materially
- Turnover increase ≤ +20%
- Fees increase ≤ +20%
- A1/A2 broker_accounting_audit both `passed=True`
- Bootstrap CI lower bound ≥ -1pp ΔCAGR

**Concentrated passes if ALL**:
- ΔCAGR ≥ -3pp (preferably positive)
- ΔMDD ≥ +10pp
- 2020 stress MDD improves toward -25% to -28%
- N=2/3/5 (no N=7)
- Rebound capture within 2 weeks of reentry_score > 0.6
- No cash trap (>30% cash for >60 days during rising market)

### G4: Output

```
outputs/integrated_challenger/
  grid_results.csv           # full matrix
  verdict.json               # best combo SHIP/PARTIAL/REJECT
  stress_window_matrix.csv   # per-window per-combo
  promotion_audit.json       # gate-by-gate detail
```

## 5. Critical files to modify

| File | Phase | Change | LoC |
|---|---|---|---:|
| `r1000_config.py` | C0.1 | kill switches + PDA weights | +50 |
| `r1000_config.py` | E5 | crisis governor config | +30 |
| `r1000_config.py` | F | hold-vs-replace config | +20 |
| `r1000_pipeline.py:1098-1108` | C0.1 | kill switch gate | +15 |
| `r1000_pipeline.py:add_total_score_columns` | D4 | PDA overlay (gated) | +30 |
| `r1000_pipeline.py` | E5 | apply_crisis_governor_to_portfolio | +200 |
| `r1000_pipeline.py` | F | replacement_swap_engine | +180 |
| `tools/run_drawdown_segment_report.py` | E1 | NEW | ~250 |
| `tools/run_crisis_signal_builder.py` | E2 | NEW | ~300 |
| `tools/run_crisis_type_classifier.py` | E3 | NEW | ~150 |
| `tools/run_cagr_preserving_crisis_governor_replay.py` | E7 | NEW | ~400 |
| `tools/run_hold_vs_replace_evaluator.py` | F | NEW | ~250 |
| `tools/run_integrated_alpha_crisis_challenger.py` | G | NEW | ~500 |
| `tests/smoke_test.py` | all | 20+ new tests | +400 |

**Total NEW**: ~2,050 LoC. **Modified**: ~525 LoC.

## 6. Safety invariants (must not regress)

1. `sec_evidence_apply_to_live_score = False` default (kill switch)
2. `pda_apply_to_live_score = False` default
3. `crisis_governor_apply_to_live = False` default
4. No hardcoded ticker references (CLSK, T1, etc.) in production code paths
5. No `report_period` used as availability date — only `accepted_at_ts` /
   `available_from_ts`
6. Static `ETF_LOOKTHROUGH` not used as production PIT evidence
7. N=7 concentrated forbidden in challenger grid
8. A1/A2 broker accounting must pass before any production weight promotion
9. 6mo consecutive SHIP verdicts before Phase C8 enables auto-promotion
10. No `--no-verify` on commits

## 7. Verification matrix

| Phase | Smoke tests | Cloud rebuild | A1/A2 gate |
|---|:-:|:-:|:-:|
| C0.1 kill switch | 4 new | ✗ (no behavior change) | ✗ |
| E1 dd audit | 3 new | ✗ (read-only) | ✗ |
| E2 crisis signals | 4 new | ✗ | ✗ |
| E3+E4 classifier+score | 5 new | ✗ | ✗ |
| E5+E6 ladders | 6 new | ✓ (governor off vs on) | ✗ |
| E7 governor replay | 5 new | ✓ (stress windows) | ✗ |
| F hold-vs-replace | 4 new | ✓ (with vs without) | ✗ |
| G integrated challenger | 8 new | ✓ (full grid) | REQUIRED for SHIP |
| C8/C9 promotion | 5 new | ✓ | REQUIRED |

## 8. Cancel-safe checkpoints

If Codex needs to pause and resume:

| Checkpoint | What to record |
|---|---|
| After C0.1 merge | branch SHA, smoke test count |
| After D1+D5+D7 merge | event parquets sample sizes |
| After E1 audit | drawdown_segments/report.md committed |
| After D3 merge | manager_pda_scores.parquet row count |
| After E7 governor replay | stress_window_metrics.csv committed |
| After G grid | grid_results.csv + verdict.json committed |

All checkpoints are git-tracked, no external state required.

## 9. Halt conditions

Codex MUST stop and request human review if:

- E1 audit reveals fundamentally different drawdown anatomy than expected (e.g.,
  main 2022 DD turns out to be from one specific position rather than systemic)
- E4 crisis_score fires false alarms in 2024-2025 normal markets > 10/year
- E7 governor replay shows MDD reduction but CAGR loss > 3pp (CAGR-preserving
  goal failed)
- G challenger grid finds no combo meeting promotion gates after full search
- A1/A2 audit gates remain false after fix attempt

In any halt: write `research/final_integrated_engine_20260524/halt_<phase>.md`
with diagnosis + proposed next steps.

## 10. Final deliverable on success

When Phase G produces a SHIP-grade combo:

1. `outputs/integrated_challenger/verdict.json` = SHIP
2. `outputs/integrated_challenger/grid_results.csv` includes winner
3. `outputs/crisis_governor_replay/stress_window_metrics.csv` shows MDD improvement
4. `research/broker_accounting_audit.json` A1+A2 both `passed=true`
5. Bootstrap CI lower bound ≥ -1pp ΔCAGR
6. Cost sensitivity at 100bps acceptable

Then create a **DRAFT** PR (not auto-merge) with:
- Title: `feat(integrated): Phase G final engine — main +Xpp / -Ypp MDD, concentrated +Zpp / -Wpp MDD`
- Body: full gate-by-gate audit table
- Label: `needs-human-approval`
- DO NOT enable auto-merge
- DO NOT change kill switch defaults in the PR

Human review → 6mo SHIP wait → Phase C8/C9 enable promotion.
