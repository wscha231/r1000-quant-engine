# Phase 15-S1a A/B Verdict — 2026-04-21

**Date**: 2026-04-21 (overnight A/B while user offline)
**Engine commit**: master at `b002f8a` (post env-override gate fix)
**Run**: `b2zq3xkam` — `PHASE_PHASE11_MULTIBAGGER_ENABLED=0 PHASE_PHASE15_S1A_FUTURE_PRUNE_ENABLED=1 py -3 run_local.py --no-collector`
**Baseline**: snapshot from `b0r5er6bz` (Phase 12 bugfix validation, cold-start clean)

## Hypothesis tested
Removing three factors from `future_winner` composite in r1000_signals.py:642-707 whose per-factor rank-IC is negative at both 1m and 3m horizons on 94 OOS months:

  - `fundamental_turnaround_acceleration_score`  w=0.50  IR_1m=-0.19  IR_3m=-0.27
  - `cashflow_inflection_under_loss_score`       w=0.35  IR_1m=-0.15  IR_3m=-0.20
  - `uptrend_breakdown_penalty`                  w=-0.30 IR_3m=-2.03 (sign mismatch)

Expected per IC audit (`research/phase15_s1_future_winner_factor_ic.csv`):
  - future_winner topn_cagr_1m +2-5pp (16 -> 18-21%)
  - main blend CAGR +0.3-0.7pp
  - concentrated CAGR +1-3pp

## Actual result

### Main blend
| metric | baseline | treatment | delta |
|---|---|---|---|
| CAGR | 22.95% | **22.49%** | **-0.46pp** |
| Sharpe | 1.1694 | 1.1477 | -0.0217 |
| MaxDD | -26.21% | **-22.18%** | **+4.03pp** |
| ending_capital_usd | $417,358 | $406,706 | -$10,653 |
| avg_turnover | 42.91% | (unreported, likely similar) | - |

### Concentrated
| metric | baseline | treatment | delta |
|---|---|---|---|
| strategy_cagr | 33.17% | **36.42%** | **+3.25pp** |
| Sharpe | 1.180 | **1.298** | +0.118 |
| MaxDD | -27.10% | -27.16% | -0.06pp |
| selected_names | 3 | 4 | +1 |

### Ship gate (Main)

| Check | Δ | Gate | Result |
|---|---|---|---|
| ΔCAGR | -0.46pp | ≥ +0.5pp | **FAIL** |
| ΔSharpe | -0.022 | ≥ -0.05 | PASS |
| ΔMaxDD | +4.03pp | ≥ -3pp | PASS (big margin) |

Main: **FAIL** ship gate on CAGR criterion.

### Ship gate (Concentrated — no formal gate but same criteria)

| Check | Δ | Gate | Result |
|---|---|---|---|
| ΔCAGR | +3.25pp | ≥ +0.5pp | **PASS** |
| ΔSharpe | +0.118 | ≥ -0.05 | **PASS (big)** |
| ΔMaxDD | -0.06pp | ≥ -3pp | PASS |

Concentrated: **STRONG PASS**.

## Interpretation

Asymmetric outcome: concentrated gains significantly, main regresses slightly. Likely reasons:

1. **Concentrated is top-few sensitive.** N=3-5 drawn from future+early pool. Cleaning the future_winner composite directly improves the few high-conviction names concentrated relies on. Sharpe 1.18 -> 1.30 is a clear signal quality improvement.

2. **Main is 18-name diversified with core dominance** (60% core / 25% future / 15% early per `defensive_drawdown_control`). The future sleeve change only affects 25% of the portfolio, diluted by core which is unchanged. Any positive effect is offset by the three removed factors' **cross-sleeve interaction** that apparently benefited main.

3. **MaxDD +4pp on main is a real win on risk-adjusted basis.** The removed factors may have contributed to tail exposure that the raw IC analysis didn't capture.

4. **uptrend_breakdown_penalty had IR_3m = -2.03.** That sign-flipped penalty was penalizing winners at 3m horizon. Removing it should help. But it also flagged genuine breakdowns during sell-offs — removing that protection may explain the main CAGR drag on regime-flip months.

## Recommendation

**DO NOT flip cfg default.** Keep `phase15_s1a_future_prune_enabled: bool = False` in production. The current `b002f8a` gate (env overrides cfg) correctly lets runs opt-in for concentrated-focused experiments without changing production main behavior.

## Follow-up options

1. **Ablation** (~60min): 3 separate QUICK A/B runs, removing one factor at a time:
   - Only `fundamental_turnaround_acceleration_score` zeroed
   - Only `cashflow_inflection_under_loss_score` zeroed
   - Only `uptrend_breakdown_penalty` zeroed

   Goal: identify the factor(s) causing main regression, ship only the subset whose individual removal leaves main flat-to-positive AND keeps concentrated improved.

2. **Concentrated-exclusive path**: apply the prune ONLY inside the concentrated backtest code path (r1000_pipeline.py line ~11939-11954 where `concentrated_score` is built). Main composite stays unchanged. This cleanly ships the concentrated +3.25pp gain without touching main.

3. **15-S1b horizon realign**: the better bet per IC audit is still training `pred_future_winner_ret` on `r_3m` target. FULL rebuild required (~2-3h). Expected to deliver the +3-5pp lift without factor-removal's cross-sleeve collateral.

## Files
- `baseline_backtest_metrics.json` — main blend baseline
- `baseline_concentrated_backtest_metrics.json` — concentrated baseline
- `treatment_backtest_metrics.json` — 15-S1a active, main blend
- `treatment_concentrated_backtest_metrics.json` — 15-S1a active, concentrated

## Status
15-S1a code shipped (commits `dfcc07c` + `b002f8a`). Default OFF per ship gate main FAIL.
Debug instrumentation removed. Toggle works correctly via env var for future experiments.
