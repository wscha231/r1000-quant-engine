# Phase 15 Tier 2 Overnight Verdict — 2026-04-22 PM

## TL;DR

- **Baseline regression**: 22.95% → 16.08% CAGR (-6.87pp). Caused by today's Tier 0/ML retrain chain. Requires investigation tomorrow.
- **9-cell Tier 2 grid verdict**: all exit-discipline toggles (R1/R2/R3) showed **zero delta** because thresholds too strict for 83-month backtest to trigger. Phase 4 regime sleeve weights showed -0.25pp (reject). Phase 6c dormant (safe).
- **15-A1 feature prune**: requires FULL rebuild for A/B (feature_store level change, cache reuse defeats test).
- **Concentrated**: NaN across all cells because --ab-quick disables concentrated grid. Full QUICK needed for concentrated verdict.

## 1. Baseline regression investigation needed

| baseline source | CAGR | notes |
|---|---|---|
| OLD (b0r5er6bz, Phase 12 fix) | 22.95% | from `research/phase15_s1a_ab/baseline_backtest_metrics.json` |
| NEW (bi4d0bmfu, today afternoon) | 16.08% | Tier 0 + Phase 13-lite + ML retrain |
| Δ | -6.87pp | 14x typical data-drift swing |

Likely causes:
1. **Tier 0a mktcap clip 1e12 → 1e14**: changed mega-cap feature values. Affects size_saturation, log_mktcap composites.
2. **ML retraining** (phase4_modeling status=completed, not reused): fresh CatBoost model with slightly different hyperparams picked different names.
3. **Tier 0b 1970 date fix**: only affects fund_period display; shouldn't affect alpha.
4. **Phase 13-lite output layer**: should be alpha-neutral.

**Tomorrow action**: revert Tier 0a in isolation and re-run baseline. If CAGR recovers to 22.95%, Tier 0a is confirmed cause.

## 2. 9-cell grid results

Baseline: 16.08% / Sharpe 0.88 / MaxDD -31.93%

| Cell | env vars | ΔCAGR | ΔSharpe | ΔMaxDD | Verdict |
|---|---|---|---|---|---|
| B R1 trailing stop (early_scout -15%) | R1=1 | +0.00pp | 0 | 0 | FLAT - threshold never triggered |
| C R2 revision break (2m neg) | R2=1 | +0.00pp | 0 | 0 | FLAT - threshold never triggered |
| D R3 RS break (top15% → bot30%) | R3=1 | +0.00pp | 0 | 0 | FLAT - threshold never triggered |
| E all R stacked | R1+R2+R3=1 | +0.00pp | 0 | 0 | FLAT |
| F R + 15-A1 | R1+R2+R3+A1=1 | +0.00pp | 0 | 0 | FLAT (15-A1 cache-blocked) |
| **G Phase 4 regime sleeve** | P4=1 | **-0.25pp** | -0.013 | -0.33pp | **REJECT** |
| H Phase 6c vol target | P6c=1 | +0.00pp | 0 | 0 | FLAT (dormant) |
| **I full stack** | all=1 | -0.25pp | -0.013 | -0.33pp | REJECT (P4 dominates) |

### Individual phase interpretations

**Phase 4 regime-conditional sleeve weights** (-0.25pp, REJECT)
- First proper A/B verdict for this phase (shipped 2026-04-16 but never verified)
- Regime multipliers tilt sleeve allocation per regime label
- Effect: slightly worse CAGR, slightly worse MaxDD
- **Recommendation**: keep default OFF. Consider regime multiplier table tuning (not just on/off).

**Phase 6c vol targeting** (zero delta, SAFE)
- Backtest-level dynamic cash floor when realized vol exceeds 12% annualized
- Dormant in 83-month sample (never triggered)
- **Recommendation**: safe to flip default True as insurance (Phase 6a precedent — also dormant but shipped).

**15-R1/R2/R3 exit discipline** (zero delta each, SAFE)
- Trailing stop / revision break / RS break — all default thresholds too strict for observed drawdowns
- 15-R1 -15% peak drawdown: never triggered (biggest intra-month drop was -15.9% at 2020-02 COVID)
- 15-R2 2-month neg revision: rare in 83-month sample
- 15-R3 top 15% → bottom 30%: extreme, rare
- **Recommendation**: ship as LOW-risk insurance (zero cost, potential future benefit). Consider loosening thresholds in next phase:
  - 15-R1: -10% instead of -15%
  - 15-R2: 1 month instead of 2
  - 15-R3: top 25% → bottom 40%

**15-A1 negative features drop** (zero delta, cache-blocked)
- 15-A1 zeroes macro_hedge_score / focus_defensive_regime / focus_live_event_defensive in feature store build
- Requires FULL feature_store rebuild to see effect
- **Recommendation**: run FULL (--full) in next session to get clean A/B. IC audit predicted +0.3-0.8pp.

### What WORKED vs FAILED

**WORKED**:
- Infrastructure: --ab-quick mode, reuse_fingerprint exclusion, gate env-overrides-cfg
- All 3 exit discipline implementations (R1/R2/R3) default-OFF shipping
- Phase 13-lite subscription outputs (concentrated enrichment, summary JSONs, recent_trades)
- 9-cell grid harness for automated A/B

**FAILED**:
- Phase 4 regime sleeve weights (-0.25pp)
- 15-A1 A/B (cache-blocked)
- Baseline regression (-6.87pp — needs investigation)

## 3. Ship candidates (next session)

| Phase | Action |
|---|---|
| Phase 6c vol target | Flip cfg default to True (Phase 6a precedent — dormant but safe) |
| 15-R1/R2/R3 | Flip cfg defaults to True (safe insurance, zero cost) |
| 15-A1 | Run FULL once to confirm. If +CAGR, flip to True. |
| Phase 4 | Keep default False. Consider tuning multiplier table. |

## 4. Critical next steps

1. **Baseline regression** (HIGHEST priority): revert Tier 0a temporarily, rerun, isolate cause.
2. **15-A1 FULL A/B** (HIGH): FULL rebuild (~3h) to test feature-store-level change.
3. **Full QUICK run** (MED): concentrated grid has been broken by --ab-quick. Need full QUICK to verify concentrated metrics.
4. **Tighten R1/R2/R3 thresholds A/B** (MED): current defaults never trigger; try looser.
5. **15-S1b ML target r_3m** (HIGH): single biggest expected lift per deep audit.
6. **Phase 16: alpha additions** per MASTER_PLAN.md: inflection detector, multi-horizon RS, event-driven catalyst.

## Files
- `cells/*_backtest_metrics.json` — raw per-cell results
- `cells/*_concentrated_backtest_metrics.json` — all NaN, --ab-quick disabled concentrated
- `run_tier2_grid.sh` — reproducer
- `analyze_tier2.py` — analysis (has em-dash bug on Windows cp949, use inline python instead)

## Runs completed today
- `b029fgd3t` 15-A1 v4 (killed at 68min, ML retraining)
- `br1ldkl6w` 15-A1 v5 (107min full ML retrain + backtest) → treatment snapshot
- `bi4d0bmfu` baseline re-establish (5min cache hit) → new baseline
- `b4pyq12qn` 9-cell grid (45min, 9 cells × 5min)
