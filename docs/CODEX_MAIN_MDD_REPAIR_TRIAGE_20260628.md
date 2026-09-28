# Main MDD Repair Triage - 2026-06-28

## Purpose

Main is now primarily an MDD problem.

The AI Capex momentum tilt from PR #199 is a credible Main CAGR candidate, but
it does not repair Main drawdown. This document records what has already failed
and defines the next non-cheating research path.

This is research-only. It must not trigger production promotion, live trading,
or a fullrun.

## Current Evidence

Clean 7Y baseline from run `28074476465`:

| Portfolio | CAGR | MaxDD | Status |
|---|---:|---:|---|
| Main | ~33.15% | -26.02% | both target floors fail |
| Concentrated | ~46.24% | -25.82% | both target floors fail |

PR #199 hook-generated Main target-book broker replay:

| Arm | CAGR | MaxDD | Sharpe | Verdict |
|---|---:|---:|---:|---|
| Baseline replay | 33.93% | -26.02% | 1.239 | reference |
| Main AI Capex momentum tilt | 34.91% | -26.04% | 1.257 | CAGR candidate only |

Interpretation:

- The AI Capex tilt is useful for Main CAGR.
- It still leaves Main below the 35% CAGR target by about 0.09pp.
- It does not fix Main MDD; MaxDD remains around -26%.
- It should not be applied to Concentrated.

## Existing MDD Repairs Already Tested

Artifacts inspected under:

`artifacts/28074476465/outputs`

### 1. Position-risk / stop overlays

| Candidate | CAGR | MaxDD | Verdict |
|---|---:|---:|---|
| `broker_position_risk_replay/main` | 28.66% | -25.77% | reject, CAGR damage too large |
| `broker_parabolic_risk_replay/main` | 31.95% | -26.46% | reject, MDD worse |

Conclusion:

Broad stop overlays are not the answer. They either fail MDD or destroy CAGR.

### 2. Cash overlay / crisis floors

`mdd_cash_overlay_research/main`:

| Variant | CAGR | MaxDD | Verdict |
|---|---:|---:|---|
| Workflow default / strong DD cap | 19.46% | -23.72% | MDD repaired, CAGR destroyed |
| Best sweep variant: `crisis_only_fast_reentry` | 30.68% | -25.32% | still fails MDD and damages CAGR |
| `late_dd_fast_release` | 32.19% | -26.46% | MDD worse |

Conclusion:

Broad cash conversion is too expensive. It is not acceptable as a mission
solution.

### 3. Simple SPY drawdown-trigger overlay

An ad-hoc research overlay on the PR #199 Main AI Capex tilt equity curve tested
SPY drawdown thresholds, temporary cash floors, and fixed hold durations.

Best target-passing shape found:

| Rule sketch | CAGR | MaxDD | Problem |
|---|---:|---:|---|
| SPY drawdown <= -3%, 25% cash floor, 21-day hold | 32.67% | -24.62% | MDD passes, CAGR fails badly |

Conclusion:

Market-level drawdown triggers can fix MDD, but only by sitting in cash too much.
They should not be promoted.

## Main MDD Window

Baseline Main MaxDD is concentrated in the COVID crash:

- peak: `2020-02-19`
- trough: `2020-03-18`
- drawdown: about `-26%`

Top peak-to-trough holding loss contributors:

| Ticker | Approx peak weight | Approx value loss |
|---|---:|---:|
| AMD | 13.4% | -$10.4k |
| PENN | 6.3% | -$7.3k |
| NOW | 11.4% | -$7.1k |
| STM | 5.7% | -$6.1k |
| UI | 4.5% | -$5.7k |
| PCTY | 5.2% | -$5.5k |
| FTNT | 5.2% | -$5.3k |
| PAYC | 5.0% | -$5.0k |
| QRVO | 5.0% | -$4.9k |
| TSLA | 6.1% | -$4.5k |

The system did sell aggressively on `2020-03-02`, but that was after the peak
and after material damage had already occurred.

## Correct Next Hypothesis

Do not continue broad cash/stop work.

The next useful hypothesis is:

> Main MDD can be repaired by reducing exposure to crash-fragile names and
> clusters when observable pre-crash or early-crash fragility is high, without
> broadly raising cash across normal bull markets.

This is a selection/risk-shaping problem, not a blanket cash problem.

## Required Next Tool

Create a cheap research screen:

`tools/run_main_crash_fragility_screen.py`

Inputs:

- Main target book
- price cache
- market/crisis state
- candidate replay features when available

Outputs:

- `outputs/main_crash_fragility_screen/summary.json`
- `fragility_bucket_report.csv`
- `mdd_window_attribution.csv`
- `report.md`

PIT features to test:

- trailing volatility / ATR
- beta or market sensitivity proxy
- distance from MA50/MA200
- 21d/63d drawdown before rebalance
- recent RS deterioration
- market state: GREEN/WATCH/DEFENSE/CRISIS
- theme/sector cluster concentration
- earnings/guidance evidence when available
- liquidity / gap risk proxy if available

Audit labels only:

- next 21d downside
- next 42d downside
- contribution to account drawdown
- MDD-window loss contribution

Acceptance to design a default-OFF hook:

- high-fragility bucket must show materially worse forward downside than low
  fragility bucket,
- result must not be explained only by February/March 2020,
- IS/OOS direction must be consistent,
- sample count must be sufficient,
- no ticker/date hardcoding,
- no forward labels in live ranking.

## Candidate Hook Only After Screen Passes

Potential env:

`PHASE_MAIN_CRASH_FRAGILITY_TRIM_ENABLED`

Possible behavior:

- Main only.
- Default OFF.
- Preserve selected ticker set initially.
- In weak market states only, trim high-fragility names and redistribute to:
  - existing lower-fragility selected names, or
  - bounded cash residual if redistribution is cap-infeasible.
- No effect in normal GREEN regime unless fragility score is extreme.

Telemetry:

- `main_crash_fragility_trim_enabled`
- `main_crash_fragility_trim_applied`
- `main_crash_fragility_score`
- `main_crash_fragility_reason`
- `pre_main_crash_fragility_weight`
- `post_main_crash_fragility_weight`
- `main_crash_fragility_delta`

## Explicit Rejections

Do not repeat these unless new evidence changes:

- broad SPY drawdown cash floor,
- broad crisis-state cash floor,
- tight hard stop / trailing stop,
- parabolic stop as currently wired,
- COVID-specific rule,
- ticker-specific exclusion list.

## Current Priority

1. Keep PR #199 as a Main CAGR candidate only.
2. Start `main_crash_fragility_screen` as the next cheap research step.
3. Only if the screen passes, implement a default-OFF Main crash-fragility trim.
4. Broker-ledger A/B is required before any fullrun.
5. Even if CAGR/MDD targets pass, `pit_universe_label_clean=false` blocks
   production promotion.

## Implementation Result: First Crash-Fragility Screen

Implemented:

`tools/run_main_crash_fragility_screen.py`

Validation:

- `tests/main_crash_fragility_screen_smoke.py`
- `tools/run_pr_validation.py --only main_crash_fragility_screen`

Clean7Y artifact application:

`artifacts/28074476465/main_crash_fragility_screen_20260628`

Summary:

| Metric | Value |
|---|---:|
| Rows | 1194 |
| Dates | 85 |
| Tickers | 324 |
| High-fragility rows | 67 |
| Low-fragility rows | 115 |
| High active years | 7 |
| High minus low 42d downside gap | -0.82pp |
| Verdict | `screen_reject_no_material_fragility_edge` |

Bucket report:

| Bucket | Rows | Avg score | Avg 21d return | Avg 42d return | Avg 42d downside | Negative 42d rate |
|---|---:|---:|---:|---:|---:|---:|
| high | 67 | 0.712 | -0.59% | 2.42% | -4.74% | 35.82% |
| medium | 1012 | 0.482 | 1.92% | 3.97% | -4.61% | 42.89% |
| low | 115 | 0.289 | 0.69% | 4.19% | -3.92% | 39.13% |

Interpretation:

- The high-fragility bucket has slightly worse 42d downside than low fragility,
  but the gap is not material enough for a hook.
- Negative 42d rate is not worse for the high bucket than for the low bucket.
- Simple volatility/ATR/MA/RS/cluster/market-state fragility is not a reliable
  Main MDD repair signal.
- A default-OFF `PHASE_MAIN_CRASH_FRAGILITY_TRIM_ENABLED` hook is rejected for
  now.

Additional quick splits:

- Top volatility names had worse downside, but also much stronger average
  forward return. Trimming them would likely cut winners.
- Broad weak-market-state and cluster exposure splits were not strong enough.
- Sector-level weak spots exist in small samples, but are not robust enough to
  become a policy rule.

Updated next step:

Do not implement a broad fragility trim. The next MDD research step, if needed,
should be a narrower stress-window attribution screen that asks whether a small
set of recurring PIT features explains the specific left-tail losses without
cutting high-volatility winners.

## Implementation Result: Stress-Window Attribution

Implemented:

`tools/run_main_stress_window_attribution.py`

Validation:

- `tests/main_stress_window_attribution_smoke.py`
- `tools/run_pr_validation.py --only main_crash_fragility_screen --only main_stress_window_attribution`

Clean7Y artifact application:

`artifacts/28074476465/main_stress_window_attribution_20260628`

Stress windows:

- `2020-02-19:2020-03-18`
- `2025-02-18:2025-04-04`

Summary:

| Metric | Value |
|---|---:|
| Stress rows | 71 |
| Stress windows | 2 |
| Tickers | 46 |
| Top predicate | `weight_top20` |
| Top predicate loss share | 57.10% |
| Top predicate rows | 25 |
| Top predicate windows | 2 |
| Verdict | `screen_pass_design_default_off_stress_hook` |

Top predicates:

| Predicate | Rows | Windows | Avg stress return | Loss share | Other avg stress return |
|---|---:|---:|---:|---:|---:|
| `weight_top20` | 25 | 2 | -31.54% | 57.10% | -22.18% |
| `weak_market_state` | 43 | 2 | -20.79% | 38.74% | -32.67% |
| `extension_top20` | 15 | 2 | -31.01% | 30.92% | -23.99% |
| `cluster_top20` | 16 | 2 | -23.33% | 29.17% | -26.10% |
| `vol_top20` | 15 | 2 | -27.03% | 26.04% | -25.06% |

Interpretation:

- The recurring stress-window signal is not broad fragility; it is large
  position size into stress windows.
- `extension_top20` is a secondary signal, but weaker than position size.
- This still does not automatically justify a cap hook because large positions
  also drive winner compounding.

## Quick Broker Check: Main Single-Name Cap

As a sanity check, Main target books were post-processed with stock-gross
preserving caps and replayed through broker ledger:

`artifacts/28074476465/main_stress_cap_broker_ab_20260628`

| Arm | CAGR | MaxDD | Sharpe | Verdict |
|---|---:|---:|---:|---|
| Baseline | 33.93% | -26.02% | 1.239 | reference |
| Main cap 10% | 32.68% | -26.03% | 1.216 | reject, CAGR lower and MDD unchanged |
| Main cap 8% | 31.05% | -26.35% | 1.185 | reject, CAGR lower and MDD worse |

Interpretation:

- Stress-window attribution correctly identifies that large positions explain a
  lot of stress losses.
- A blunt lower Main cap is still not useful; it cuts winner compounding and
  does not fix full-window MDD.
- Do not implement a generic Main single-name cap reduction.

Updated next step:

The next MDD candidate must be more selective than `weight_top20` alone. It
should combine large position size with an additional PIT stress condition such
as extreme extension plus early market damage, and it must prove broker-ledger
MDD improvement without the cap10/cap8 CAGR collapse.

## Implementation Result: Stress-Condition Cap Broker A/B

Implemented:

`tools/run_main_stress_condition_cap_broker_ab.py`

Validation:

- `tests/main_stress_condition_cap_broker_ab_smoke.py`
- registered in `tools/run_pr_validation.py`

Clean7Y artifact application:

`artifacts/28074476465/main_stress_condition_cap_broker_ab_20260628`

Arms:

- `baseline`
- `large_ext_cap10`
- `large_ext_cap11`
- `large_ext_weak_cap10`
- `large_ext_weak_cap11`
- `large_ext_vol_cap10`
- `large_ext_fragile_cap10`

All non-baseline arms preserve selected tickers and cash policy. They only cap
already-selected Main names when PIT-observable conditions are true:

- large position size (`weight_rank >= 0.80`)
- extension (`ma200_extension_rank >= 0.80`)
- optional weak market state, high volatility, or high crash-fragility score

Broker replay result:

| Arm | Applied rows | CAGR | MaxDD | Sharpe | Verdict |
|---|---:|---:|---:|---:|---|
| Baseline | 0 | 33.93% | -26.02% | 1.239 | reference |
| `large_ext_cap10` | 79 | 33.04% | -26.02% | 1.225 | reject, CAGR damage |
| `large_ext_cap11` | 67 | 33.56% | -26.02% | 1.234 | reject, no MDD edge |
| `large_ext_weak_cap10` | 32 | 33.83% | -26.02% | 1.239 | reject, no MDD edge |
| `large_ext_weak_cap11` | 27 | 33.96% | -26.02% | 1.241 | reject, no MDD edge |
| `large_ext_vol_cap10` | 32 | 33.72% | -26.02% | 1.241 | reject, no MDD edge |
| `large_ext_fragile_cap10` | 0 | 33.93% | -26.02% | 1.239 | blocked, no applied rows |

Interpretation:

- The predicate fired for multiple non-baseline arms, so this is not a no-op.
- MaxDD stayed unchanged in every fired arm. The Main left-tail problem is not
  fixed by monthly stock-level conditional caps.
- This closes the cheap cap/fragility path for Main MDD repair. Broad cash,
  stop overlays, broad fragility, blunt caps, and stress-condition caps have all
  failed on broker-ledger evidence.

Updated next step:

Do not add more monthly stock-level cap variants. The remaining Main MDD repair
path has to move to a different mechanism:

1. intramonth/fast-crash market defense that can react before the monthly target
   book is updated;
2. explicit index/market hedge research, measured as broker-ledger overlay and
   not as production trading;
3. or governance review of the Main target, because the current monthly long-only
   target-book levers repeatedly fail to move the 2020 max drawdown without
   damaging CAGR.

## Implementation Result: Intramonth Event-Defense Broker A/B

Implemented:

`tools/run_main_event_defense_broker_ab.py`

Validation:

- `tests/main_event_defense_broker_ab_smoke.py`
- registered in `tools/run_pr_validation.py`

Clean7Y artifact application:

`artifacts/28074476465/main_event_defense_broker_ab_20260628`

This harness tests the next mechanism after monthly caps failed: event-driven
target books and daily crisis-cash snapshots. It is still research-only and
uses the same broker-ledger replay.

Arms:

- `baseline_monthly`
- `crisis_cash_preserve_default`
- `crisis_cash_preserve_strict`
- `crisis_cash_preserve_strict_fast_release`
- `event_default`
- `crisis_cash_strict`
- `crisis_cash_strict_fast_release`
- `event_default_no_cluster_caps`

The `crisis_cash_preserve_*` arms are the cleanest test: they apply daily crisis
cash changes without position exits and never lower the monthly target-book cash
floor. This avoids the accidental "defense by raising stock exposure" failure
mode.

Broker replay result:

| Arm | Events | Exits | CAGR | MaxDD | Sharpe | Verdict |
|---|---:|---:|---:|---:|---:|---|
| Baseline monthly | 0 | 0 | 33.93% | -26.02% | 1.239 | reference |
| `crisis_cash_preserve_default` | 82 | 0 | 32.93% | -26.99% | 1.219 | reject, MDD worse and CAGR damage |
| `crisis_cash_preserve_strict` | 88 | 0 | 31.47% | -25.49% | 1.197 | reject, partial MDD improvement but CAGR damage |
| `crisis_cash_preserve_strict_fast_release` | 81 | 0 | 31.73% | -25.49% | 1.203 | reject, partial MDD improvement but CAGR damage |
| `event_default` | 449 | 314 | 24.22% | -42.85% | 1.022 | reject |
| `crisis_cash_strict` | 186 | 98 | 32.17% | -36.33% | 1.118 | reject |
| `crisis_cash_strict_fast_release` | 179 | 98 | 32.46% | -36.95% | 1.123 | reject |
| `event_default_no_cluster_caps` | 449 | 314 | 24.33% | -49.55% | 0.961 | reject |

Interpretation:

- Intramonth cash overlays do fire; this is not a no-op.
- The cleanest strict cash-only arms move MaxDD from `-26.02%` to `-25.49%`,
  but still miss the `-25%` target and reduce CAGR by more than 2pp.
- Event target books with position exits are much worse. They introduce too
  many exits and whipsaw the portfolio.
- Even if paired with the PR #199 Main AI Capex CAGR candidate, the strict
  cash-only arms are not close to the mission tradeoff.

Updated next step:

The cheap Main MDD paths are now exhausted:

- monthly cash/stop overlays: rejected
- broad fragility: rejected
- blunt caps: rejected
- stress-condition caps: rejected
- intramonth event/cash overlays: rejected

The remaining honest paths are:

1. explicit hedge research measured as a broker-ledger overlay, not production;
2. structural portfolio redesign that changes the Main objective/selection mix;
3. governance review of whether `Main MDD >= -25%` is realistic for the current
   long-only monthly target-book architecture.
