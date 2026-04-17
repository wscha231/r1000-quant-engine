# Execution Plan — Post-Phase-8 Roadmap

**Date**: 2026-04-17
**Status**: Phase 8 FULL rebuild in progress (started 2026-04-17 05:00:19 UTC, ETA ~2-2.5h)
**Purpose**: User explicitly asked to stop patching, audit Drive, then establish a prioritised plan. This doc is the plan.

---

## 0. Drive audit — what actually ran and produced results

Six archived runs span 2026-04-15 to 2026-04-17. For each, pulled `backtest_metrics.json` from the archive:

| Timestamp (UTC) | Commit | Engine version label | CAGR | Sharpe | MaxDD | IR | Avg turnover | Avg names |
|---|---|---|---|---|---|---|---|---|
| 04-15 09:40 | 05ffbde | phase1-ops-layer-perf1 | 17.81% | 1.02 | -21.67% | 0.44 | 47.4% | 25.1 |
| 04-15 14:15 | aa8b731 | phase1-ops-layer-perf1 | 19.74% | 1.02 | -20.65% | 0.55 | 48.8% | 19.9 |
| 04-16 08:02 | d277a21 | phase1+2-turnaround-industry | 18.48% | 0.99 | -26.54% | 0.46 | 47.0% | 25.0 |
| **04-16 11:14** | **1d4fb40** | **phase2-keepcols-fix** | **20.10%** | **1.08** | **-23.60%** | **0.58** | **46.9%** | **25.8** |
| 04-16 17:02 | 8b10bf4 | phase2-keepcols-fix (Phase 3 harden) | 17.80% | 0.95 | -28.18% | 0.40 | 48.6% | 26.6 |
| 04-17 08:09 | 914558f | phase5-leader-laggard (+ Phase 6a/b/c + 7a) | 15.44% | 0.84 | -26.34% | 0.20 | 49.5% | 21.0 |

**Drive critical observations**:
- The BEST measured CAGR (20.10%) was the SIMPLEST configuration — just Phase 1+2 with the keepcols fix.
- Every subsequent "enhancement" (Phase 3, Phase 5) made things WORSE, not better.
- The 04-17 dilution fix (c4d50fd) and Phase 8 code have **never produced a completed archived run** (the run crashed on the hard_sanitize dedup bug).

## 1. Honest diagnosis — what the 2-day patch cycle actually achieved

### What worked
- Phase 2 keepcols-fix (1d4fb40): restored Phase 2 columns that were being dropped silently. CAGR 18.48% → 20.10%.
- Phase 1 ops-layer (aa8b731): gave a 2pp boost from 17.81% → 19.74%.

### What didn't work (empirically)
- **Phase 3 sleeve renorm** (8b10bf4): regressed CAGR to 17.80%. Already REJECTED.
- **Phase 5 sub-industry leader/laggard** (914558f): regressed CAGR to 15.44% via dilution bug. Dilution fix (c4d50fd) applied in code but not yet ship-tested.

### What's untested
- **Phase 8 (a/b/c/d)** — 13 commits of new logic. NEVER successfully completed a run. The run currently in progress is the first attempt.

## 2. Why "top30 안 바뀐다" — user-accurate observation

User reported that top30 picks look similar across many patches despite weight changes. This is accurate because:

1. **Dominant factors are unchanged across Phase 1-8**:
   - SAGE composite (IC 0.022)
   - future_winner_scout_score (IC 0.014)
   - long_hold_compounder_score (IC 0.005)
   - moat_quality_blueprint_score (IC 0.008)
   
   These collectively produce ~70% of the sleeve composite weight. Adding 5-10 new Phase 1-5 factors with |w| = 0.10-0.55 gets DILUTED by row_mean before it can shift the ranking.

2. **Sleeve argmax is deterministic**: same factor values → same sleeve assignments → same names in top N per sleeve.

3. **Hold persistence bonus** (Phase 8a.4, not yet tested) EXPLICITLY rewards sticky picks. This is intentional (reduces turnover cost) but amplifies the "안 바뀐다" perception.

4. **Factor accretion without pruning**: adding new factors without removing noise ones creates a high-dimensional fuzzy ranking. Fuzzy = sticky.

**Real fix** for top30 variety (not just CAGR improvement):
- Phase 9 sleeve thesis-gate redesign (core/future/early explicit archetype gates) — different sleeves pick structurally different names.
- Factor reduction (153 noise factors out) — let strong signals shift the ranking.

## 3. Realistic CAGR ceiling — cold assessment

### What the data says
Over 6 runs with increasing complexity: CAGR peaked at 20.10% with the simplest configuration. Adding Phase 3/5 monotonically regressed.

### What Phase 8 MIGHT add (predictions from DIAGNOSIS_COUNTERFACTUAL.md)
- IC-proportional reweighting (Phase 8a.1 + 8d.1): +3-5pp (theoretical)
- Long-lookback momentum (Phase 8b.1): +3-7pp (theoretical)
- Mega-cap + growth-adj valuation (Phase 8c): +2-4pp (theoretical)
- Hold persistence (Phase 8a.4): +1.5pp (turnover cost saving, well-defined math)
- Score bug fix (Phase 8a.5): +0.3pp (one-month corruption)

Total theoretical boost: +10-17pp. But **predictions aren't data**. Realistic realisation rates from past Phase additions: 0-50% of predicted.

### Scenarios for Phase 8 outcome

| Scenario | CAGR | Realisation | Next |
|---|---|---|---|
| **Best case** | 25-28% | 60%+ of predictions | SHIP, proceed to Phase 9 cleanup |
| **Realistic** | 21-24% | 30-50% | Partial ship — A/B isolate which sub-phase actually contributed |
| **Worst case** | 15-18% | 0% (another regression) | Roll back to 1d4fb40 baseline (20.10%). Rethink strategy. |

### If CAGR caps at ~20-22%: honest architectural questions

Our framework: R1000 universe + monthly rebalance + 25-ish names + r_1m ML target + factor composite sleeves.

Candidates for STRUCTURAL change (beyond more factor-tuning):
1. **Rebalance horizon**: Monthly → Quarterly. 3x lower turnover, but requires r_3m or r_6m training target.
2. **Portfolio size**: Top 25 → Top 10. Higher concentration, higher CAGR variance, higher MaxDD. User has already validated the concentrated 3-name run (CAGR ~20% with MaxDD -37%).
3. **ML target horizon**: r_1m → r_12m (Phase 8e deferred). 2-4x stronger factor IC at 12m per diagnosis.
4. **Universe expansion**: R1000 → R1000 + R2000 mid-cap SaaS names. More early-stage inefficiency to exploit.
5. **Long-only → long-short**: market-neutral component to extract factor alpha independent of market direction.

None of these are cheap. Each requires ~1 week of dedicated work.

## 4. Prioritised roadmap — staged execution

### Stage 0: Let the current run finish (now, ~2h)
- Cell 4 is rebuilding feature_store → walk-forward → latest scoring
- NO other changes until it completes
- When done: paste Cell E output, we verdict together

### Stage 1: Verdict handling (immediate, after Cell 4 finishes)

**Stage 1a (SHIP path)**: CAGR ≥ 23% AND Sharpe ≥ 1.0
1. Archive this as the new baseline
2. Update SESSION_HANDOFF.md with the ship metric
3. Proceed to Stage 2

**Stage 1b (PARTIAL path)**: CAGR 20-23%
1. Run 4 QUICK_RESCORE A/B with one sub-phase disabled at a time (each 20 min, total ~90 min)
2. Identify the sub-phase(s) that hurt
3. Disable their defaults in cfg
4. Re-run QUICK_RESCORE
5. Ship the subset that works

**Stage 1c (REGRESS path)**: CAGR < 20%
1. Roll back to 1d4fb40 (Phase 2 keepcols-fix only). Make this the official baseline.
2. Phase 8 branches to a `phase8-experimental` directory for future re-evaluation.
3. Proceed to Stage 2 with the simpler 20.10% foundation.

### Stage 2: Cleanup (1-1.5 day, Phase 9 Subtractive + Refactor Phase A)

Regardless of Stage 1 outcome, the following is worth doing:
1. **Phase 9 Subtractive** (per ARCHITECTURE_REVIEW.md §7):
   - Delete Phase 3 / Phase 5 infrastructure (they're proven regressions)
   - Delete 153 noise factors (from DIAGNOSIS_FACTOR_IC)
   - Consolidate 6-factor industry cluster → 1 composite; 3-factor revision cluster → 1; 3-factor growth-onset cluster → 1
   - Target: 27k lines → 12-15k lines
2. **Refactor Phase A** (per REFACTOR_PLAN):
   - 5 modules + facade (config, helpers, features, signals, pipeline)
   - `@module_boundary` decorator on all public functions
   - `COLUMN_OWNERSHIP` registry
   - `module_contribution_report.csv` post-backtest
3. **Sleeve thesis-gate redesign** (per §6b of ARCHITECTURE_REVIEW, user-validated):
   - Replace argmax with eligibility gates
   - Core: mega-cap rule OR mature quality
   - Future: mid-large cap + scaling-up growth
   - Early: EPS turn-positive OR technical breakout (golden cross / MA200 break) OR value inflection

### Stage 3: Architectural experimentation (optional, ~1 week)

If Phase 9 ships but CAGR still caps at 20-22%, try ONE of these (don't combine):
1. **Quarterly rebalance A/B** — single QUICK_RESCORE change + re-backtest
2. **Top-10 concentration A/B** — change `top_n` config, re-backtest
3. **Phase 8e r_12m ML proper** — requires walk-forward refactor (1-2 days dedicated)
4. **Universe expansion** — add R2000 names (1 week dedicated)

Choose based on which gap is biggest.

### Stage 4: Stabilise as production system

Whatever ships from Stage 1-3 becomes the production baseline:
- Frozen code
- Frozen feature set
- Monthly rebalance cadence
- Operator ready for real capital

Only change this baseline via a formal "new phase" gate:
- Factor IC measured BEFORE code commit
- A/B gate ≥ +0.5pp CAGR or ≥ +0.1 Sharpe
- Never add code for theoretical reasons alone

## 5. Rules going forward (from the 2-day pain lesson)

| Anti-pattern we fell into | New rule |
|---|---|
| "Add phase, toggle off if bad" — led to 1100 lines of dead code | Delete rejected phases. git history is the archive. |
| "More factors = more alpha" — but 59% are noise | New factor requires measured IC > 0.01 on historical data BEFORE commit. |
| "Implement first, measure second" | Measure first, commit only if empirical. |
| "Edit 27k lines and spot-check by grep" | Modules + observability + @module_boundary before new feature work. |
| "Patch mode: fix symptom, rerun" | Root-cause mode: understand why, then fix once. |

## 6. The specific "30% CAGR" ambition — honest framing

From Drive data over 6 runs:
- 20.10% is the empirical ceiling we've achieved.
- Every theoretical improvement (Phase 3/5) regressed or flatlined.
- Predictions of +10-15pp boosts from Phase 8 should be treated as optimistic.

**30% CAGR is NOT impossible, but it's NOT a simple factor-tuning exercise.** It requires:
- Either exceptional signal quality (rare — we'd need IC 0.1+)
- OR structural changes (concentration / horizon / universe / long-short)

Realistic next 6 weeks:
- Week 1: Phase 8 ship (CAGR 22-25% if successful)
- Week 2: Phase 9 cleanup (same CAGR, but maintainable)
- Week 3-4: structural experiment (quarterly rebalance or top-10 or r_12m ML). Could push to 25-28%.
- Week 5-6: stabilisation + operator validation.

Getting to 30% specifically requires Week 3-4 experiments to hit their high end AND subsequent tuning to extract the remaining 2-3pp.

## 7. Immediate action (this session only)

1. Wait for Cell 4 to finish (~2h)
2. Paste Cell 4 final output + Cell E to chat
3. Make the Stage 1 verdict call together
4. Commit the appropriate Stage 2 or 3 action sequence
5. Nothing else until Cell 4 finishes

No more patches tonight unless Cell 4 crashes.

## 8. Meta-lesson

The user's instinct to pause and ask for a plan — twice now, in the cold-assessment request AND this one — was the most valuable input of the 2-day sprint. The patch-then-measure loop produces false velocity (many commits) but no verified progress. Every major improvement on this project is going to come from the plan-then-measure discipline.

This document is the first proper plan. Amendments to it should be explicit; silently drifting back to patch mode is the failure mode to watch for.
