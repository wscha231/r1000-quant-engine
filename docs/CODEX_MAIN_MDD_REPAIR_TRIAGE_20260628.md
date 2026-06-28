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
