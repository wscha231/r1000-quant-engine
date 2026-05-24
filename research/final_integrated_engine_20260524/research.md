# Final Integrated Engine — Research

**Date**: 2026-05-24
**Status**: Pre-implementation research synthesis
**Owner**: Codex (final integrated engine agent)
**Parent spec**: `CODEX_HANDOFF_PLAN_C_V3_5_20260520.md` (v3.6 addendum §16-§23)

## 1. Problem statement

Current r1000-quant-engine has two stable portfolios validated by official
broker-ledger next-close replay:

| Portfolio | CAGR | MDD | Sharpe |
|---|---:|---:|---:|
| main | 20.35% | -33.45% | 0.991 |
| concentrated | 36.41% | -38.45% | 1.186 |

Research backtest output (`outputs/backtest_metrics.json` 29.19% / -17.46%)
is significantly more favorable but does not include integer shares, fees,
cash ledger, and has unresolved A1/A2 broker-accounting audit gates
(`delisted_cost_basis_fallback_eliminated=false`,
`survivorship_coverage_audited=false`). Promotion decisions must use only the
broker-ledger numbers.

Two crisis events dominate the MDD profile:
- **Main**: 2021-11-19 peak → 2022-10-14 trough (slow bear, rate hikes)
- **Concentrated**: 2020-02-19 peak → 2020-03-16 trough (COVID shock crash)

The user has asked for a system that:
1. Improves official broker-ledger CAGR (not research metrics)
2. Reduces MDD without sacrificing CAGR (no permanent cash defense)
3. Detects future winners + tenbagger candidates early via 13F/Form 4/13D/ETF
4. Handles 2020-style shock crashes and 2022-style slow bears differently
5. Validates everything with broker-ledger replay (legacy/proxy numbers ignored)

## 2. Why prior defense attempts hurt CAGR

The agent (and prior loop iterations 1-6 on `codex/broker-ledger-replay-foundation`)
attempted MDD reduction via cash policy adjustments + DD circuit breakers. Result:
average cash 18.94% over 83 months; main 28% cash in Feb 2026; early_scout = 3
(below SHIP gate of 4); recurring PARTIAL verdicts.

Root cause chain (Part B audit §S2-1 to §S2-5):
```
growth_floor_min_signal=0.34 too high
  → early_scout target reverts to base 0.10
  → defensive_drawdown_control policy auto-selected
  → cash_target_mild_risk_cap=0.18 baseline
  → DD breaker thresholds [0.08, 0.15, 0.25] too aggressive
  → +10% cash overlay
  → 28% observed cash + early_scout=3 + PARTIAL verdict
```

The defense was **too blunt**: it raised cash uniformly, sold winners along with
broken positions, and re-entered slowly. CAGR fell proportionally.

## 3. Hypothesis: CAGR-preserving defense

Drawdown asymmetry math:
- -30% drawdown requires +42.9% to break even
- -40% drawdown requires +66.7% to break even

If even a portion of the worst crisis drawdowns is avoided (without permanent
cash drag), compound returns improve. The defense must be **surgical**:

1. **Normal markets**: cash 0-5% (let winners run)
2. **Caution zone**: throttle new buys, hold existing winners, trim only broken
3. **Defense zone**: trim broken high-beta, prefer replacement over cash
4. **Crisis zone**: reduce concentrated exposure 30-50%, ladder re-entry

Key insight: **replacement > cash**. When a broken position is sold, swap into
a stronger leader if available, defensive leader if crisis, cash only as
last resort.

## 4. Crisis archetypes (different defense profiles)

### 4.1 Shock crash (2020 COVID archetype)
- Fast index drop (8%+ in 5 trading days)
- VIX spike to >50 (z-score > 2.5)
- Concentrated exposures take heaviest damage
- Defense: fast exposure cut
- Re-entry: fast (4-6 weeks once VIX normalizes + breadth thrust)

### 4.2 Slow bear (2022 rate-hike archetype)
- Index below MA200 for 30+ days
- Rising 10Y yield with credit spread expansion
- Growth/momentum names break first
- False rebounds common
- Defense: gradual exposure cut
- Re-entry: slow, quarter-by-quarter confirmation, growth buys throttled

### 4.3 Credit crisis (2008 archetype, hopefully never)
- HY/IG spread z-score > 2.0
- Financial sector damage
- Defense: fast exposure cut
- Re-entry: wait for credit spread stabilization before any add

### 4.4 Normal pullback (frequent)
- Index drawdown 3-8%, VIX z-score 0.5-2.0
- No defense action — let winners ride
- Avoid false alarms

### 4.5 Recovery (post-crisis re-entry)
- VIX z-score < 0.5, index above MA50
- Breadth thrust (advance-decline slope > 0.3)
- Action: re-entry ladder activates per `reentry_score` thresholds

## 5. Smart Money / PDA as confirmation, not primary

Prior Plan C v3.5 PDA framework (4-stream: 13F + Form4 + 13D + ETF) is correct
in extraction methodology but should NOT be the primary selector. Empirical
evidence from `codex/smart-money-broker-ablation` (PR #25):

> "SEC-only broker grid reached CAGR 22.00% but MDD -35.74%, promotion blocked."

The SEC stream alone is high-variance. It must combine with Future Winner
core (existing primary selector) as a confirmation layer:

- **Future Winner Core** = primary alpha (proven)
- **Smart Money Confirmation** = filter (catches T1 Energy / CLSK-style breakouts)
- **Post-Disclosure Alpha** = early discovery (tenbagger watchlist + replacement pool)
- **ETF / Theme** = industry confirmation
- **Crisis Governor** = MDD protection
- **Hold-vs-Replace** = preserve alpha during volatility
- **Broker-Ledger Gate** = honesty check

## 6. CLSK / T1 Energy pattern generalization

The user's mention of CLSK (CleanSpark) and T1 Energy as examples of "small
specialist manager buy → outperformance" must be encoded as a PATTERN, not
hardcoded tickers:

Generalized signal (Phase D3 manager_pda_scores.parquet):
```
high-PDA manager with:
  - market_cap_bucket = small or micro
  - position_type = new
  - manager_aum_bucket = small or mid
  - issuer_float_pct_added > 1% (CLSK pattern — meaningful float impact)
  - 2+ converging managers within 30 days
```

This generalization can detect future CLSK-class breakouts without bias to
specific tickers.

## 7. Target metrics (broker-ledger)

| Portfolio | Metric | Current | Phase 1 (3mo SHIP) | Final (6mo SHIP) |
|---|---|---:|---:|---:|
| main | CAGR | 20.35% | ≥ 20% | 25-30% |
| main | MDD | -33.45% | ≤ -25% | ≤ -15% |
| main | 2022 stress MDD | ~ -33% | ≤ -25% | ≤ -20% |
| main | avg cash | ~18% | ≤ 8% | ≤ 5% |
| concentrated | CAGR | 36.41% | ≥ 33% | 40-50% |
| concentrated | MDD | -38.45% | ≤ -28% | ≤ -18% |
| concentrated | 2020 stress MDD | -38% | -25% to -28% | -20% |
| concentrated | N | varies | 3 or 5 (NEVER 7) | 3 or 5 |

## 8. Verification windows

Mandatory stress windows for every challenger run:

| Window | Crisis type | Why |
|---|---|---|
| 2020-02-01 to 2020-05-31 | shock_crash | Concentrated worst case |
| 2021-11-01 to 2022-12-31 | slow_bear | Main worst case |
| 2024-01-01 to 2024-12-31 | mixed | Recent year sanity |
| 2025-01-01 to latest | live tracking | Most recent forward walk |

For each window, measure:
- CAGR with vs without governor
- MDD with vs without governor
- Rebound capture (days to recover 80% of peak)
- Re-entry lag (days from reentry_score > 0.40 to exposure increase)
- Cash trap days (>25% cash while SPY rising)
- False alarm count (defense triggered but no DD materialized)
- Turnover + fees impact

## 9. Open questions for empirical validation

1. **Does Phase E1 drawdown segment audit reveal that the engine held losers
   too long?** If yes, Phase F replacement discipline matters most.
2. **Is the 2022 slow bear primarily about new-buy throttling, or about trim
   timing?** Phase E2/E3 should distinguish.
3. **Can crisis_score detect 2022 trough early enough?** If detection lags
   30+ days, re-entry should be more aggressive than ladder suggests.
4. **Is concentrated-3 (N=3) safer than concentrated-5 in 2020 shock?** Counter-
   intuitive — smaller N may concentrate into highest-conviction names that
   defend better.
5. **Does Smart Money confirmation hurt during fast melt-up phases (2021 Q1)
   where retail momentum outruns institutional?** May need regime conditional.

## 10. Confidence assessment

| Component | Confidence | Notes |
|---|---|---|
| Future Winner core | High | Existing, validated |
| PDA framework (Phase D) | Medium | Manager_alpha exists, multi-bucket scoring novel |
| Crisis governor (Phase E) | Medium | Drawdown segment audit will guide design |
| Hold-vs-Replace (Phase F) | Medium-Low | New discipline, depends on replacement pool quality |
| Integrated challenger (Phase G) | Medium | Grid search infrastructure exists (auto_policy_challenger) |
| Promotion gate | High | Broker-ledger + A1/A2 well-defined |
| Final integrated CAGR 30%+ | Low-Medium | Aspirational, must be empirically validated |

**Recommendation**: Proceed with Phase E1 (drawdown segment audit) FIRST as
truth-finding step. The audit will reveal whether the 2022 main DD was from
holding losers or from late new-buy throttle, which determines whether
Phase E or Phase F is the higher-leverage track.

## 11. Next document

See `plan.md` for the concrete implementation roadmap, branch strategy, and
file-level edits.
