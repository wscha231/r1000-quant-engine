# CODEX Momentum and Regime Research Tracks - 2026-07-04

## Purpose

This document parks the momentum and market-regime work as a research-only backlog.
It is not a new production policy, not a fullrun trigger, and not a reason to
interrupt the current execution queue.

Current priority remains:

1. Finish the Concentrated replacement-quality candidate only under fixed-book
   and event-matched evidence.
2. Keep W1 target-book control reproduction moving.
3. Keep production blocked while `pit_universe_label_clean=false`.

Track M and Track R are added because the system is structurally a concentrated
long-only momentum system, and the next durable improvements should understand
that identity rather than add more disconnected alpha hooks.

## System Identity

AlphaOps vNext is best described as:

> Concentrated long-only cross-sectional momentum, with industry momentum,
> 52-week-high leadership, trend filters, cash/regime risk controls, and
> fundamental confirmation where PIT data exists.

Mapped to known factor families:

- Cross-sectional RS versus SPY/QQQ: cross-sectional momentum.
- Industry and group RS: industry momentum.
- O'Neil leadership and 52-week-high proximity: 52-week-high momentum.
- MA50/MA200 exit ladder: time-series trend control.
- Regime cash and crisis capacity: rough volatility/regime management.
- Earnings or actual-results overlays: earnings momentum / PEAD direction,
  but only when PIT evidence exists.

The research question is not "is this momentum?" It is:

1. How much of the realized return is generic momentum beta?
2. How much is implementation alpha from selection, concentration, timing,
   replacement quality, and risk controls?
3. Where does long-only momentum fail: post-trough re-entry delay, short-horizon
   reversal, volatility spikes, or regime-dependent scoring?

## Non-Negotiables

- No production promotion.
- No live trading.
- No fullrun from this document alone.
- No short side.
- No all-in/all-out regime switch.
- No volatility scaling up.
- No broad gross-floor revival.
- No tight-stop revival.
- No full 12-1 rebalance rewrite.
- No one-month reversal entry rule without measured evidence.
- No market-timing or recession-forecasting claim.
- Forward returns are audit labels only.
- All policy hooks remain default OFF and require applied-count proof.
- Any current-market label must come from data computed by Track R, not from
  commentary.

## Queue Placement

Track M/R ordering:

- M1, M2, R1, R2 are background research audits.
- M3 can move forward when an A-D slot is free because it directly tests
  post-trough re-entry delay.
- M4, R3, and R4 are policy-candidate work only after their audits pass.
- These tracks must not block the current Concentrated replacement-quality
  candidate or W1 control-reproduction work.

External review routing:

- GPT Pro: governance wording, service-facing expectation language, public
  display constraints, cash-carry/regime-contract decisions.
- Claude: code/path red-team only after M1/R1 outputs exist, or before turning
  M3/M4/R3/R4 into hooks.
- Codex: implementation, fixed-book audits, smoke tests, reports, and gating.

## Track M - Momentum Identity and Failure Modes

### M1. Momentum Beta Decomposition

Goal:
Quantify how much return is generic momentum beta versus implementation alpha.

Build:

- Internal 12-1 cross-sectional momentum factor from the same price cache.
- Monthly portfolio excess return series for Main and Concentrated.
- Regression table:
  - market beta
  - internal momentum beta
  - residual alpha
  - t-stat style diagnostics, if sample size permits

Outputs:

- `outputs/momentum_beta_decomposition/summary.json`
- `outputs/momentum_beta_decomposition/factor_returns.csv`
- `outputs/momentum_beta_decomposition/regression_table.csv`
- `outputs/momentum_beta_decomposition/report.md`

Acceptance:

- Informational only.
- Add `momentum_factor_neutral_excess` as a forward-service health metric if
  the factor series is stable.
- Do not change selection or weights.

Caveat:

- While `pit_universe_label_clean=false`, this is research-only and may inherit
  survivorship bias from the available universe.

### M2. RS Horizon IC Audit

Goal:
Measure whether short-horizon RS is useful for entry, or whether it fights
short-term reversal.

Inputs:

- Candidate/replay rows with PIT RS features where available:
  - 1w
  - 1m
  - 3m
  - 6m
  - 12m
- Forward 63d/126d excess labels as audit-only outcomes.

Rules:

- Separate entry-side scoring from exit/warning logic.
- Do not remove 1w/1m from exits just because entry IC is weak.
- Do not use forward labels in ranking.

Outputs:

- `outputs/rs_horizon_ic_audit/summary.json`
- `outputs/rs_horizon_ic_audit/ic_by_horizon.csv`
- `outputs/rs_horizon_ic_audit/ic_by_portfolio.csv`
- `outputs/rs_horizon_ic_audit/report.md`

Gate:

- If 1w/1m entry-side IC is <= 0 while the current entry stack gives those
  features positive score weight, create a backlog item to demote those horizons.
- No immediate policy hook.

### M3. Post-Trough Re-Entry Lag Audit

Goal:
Test the long-only momentum weakness most relevant to this system: missing the
early V-shaped rebound because cash stays high after a drawdown.

Episodes to measure:

- 2020 trough and rebound.
- 2022 trough and rebound.
- 2024-08 correction and rebound.
- 2025 correction and rebound, if data quality supports it.

Metrics:

- Months from trough to normalized stock gross.
- Cash level during first 63d/126d rebound.
- CAGR or return foregone versus:
  - hold-through baseline
  - SPY/QQQ rebound
  - raw candidate rotation, where available
- Portfolio drawdown impact.

Outputs:

- `outputs/reentry_lag_audit/summary.json`
- `outputs/reentry_lag_audit/episode_metrics.csv`
- `outputs/reentry_lag_audit/report.md`

Gate:

- If measured foregone CAGR impact is >= 1.0pp and appears in at least two
  episodes, authorize one fixed-book breadth-thrust re-entry candidate.
- If concentrated in one episode only, record as diagnostic and do not build a
  hook.

### M4. Asymmetric Volatility Brake

Goal:
Test the only volatility-management idea not already falsified: reduce risk
when portfolio volatility is extreme, but never scale up exposure.

Rules:

- Down-only gross adjustment.
- Portfolio-level, not per-name vol weighting.
- No gross increase.
- No bull-floor or broad gross-floor revival.
- Fixed-book first.

Candidate:

- If realized 20d or 21d portfolio volatility is above a predeclared percentile,
  reduce stock gross to a floor no lower than 60%.
- Release with hysteresis.

Gate:

- MaxDD improves by >= 1.0pp.
- CAGR drag is no worse than -0.5pp.
- Fires in at least two stress eras.
- OOS does not collapse.
- If it only helps one crash or behaves like a hidden cash overlay, reject.

## Track R - Regime Nowcast and Conditional Offense

### R1. Composite Bear / Correction Dial

Goal:
Create a nowcast dial that classifies the current market state. It must not be
market forecasting and must not force trades.

Candidate signals:

1. 10y minus 3m yield curve.
2. High-yield OAS widening.
3. Breadth above MA200 and breadth divergence.
4. VIX level or percentile.
5. Defensive sector RS versus market.
6. Sahm / unemployment trend.
7. SPY 200dma slope and price position.
8. Distribution-day count.
9. New-high minus new-low breadth, if available.
10. Earnings revision breadth, only after W4 PIT feed exists.

Coverage rules:

- Emit per-signal coverage.
- Missing signals are neutral, not false pass.
- Do not invent VIX3M term-structure if not collected.
- Do not claim an earnings-revision signal before PIT feed exists.

States:

- BULL
- LATE_CYCLE
- CORRECTION
- BEAR
- RECOVERY

Outputs:

- `outputs/regime_nowcast_dial/summary.json`
- `outputs/regime_nowcast_dial/signal_panel.csv`
- `outputs/regime_nowcast_dial/state_history.csv`
- `outputs/regime_nowcast_dial/report.md`

Gate:

- Informational only.
- Feed W7 backend alerts and reports.
- No scoring change from R1 alone.

### R2. State-Conditional IC Audit

Goal:
Test whether momentum features and turnaround/oversold-value features behave
differently across R1 states.

Feature families:

- Momentum:
  - RS 3m/6m/12m
  - industry RS
  - 52-week-high leadership
- Turnaround / contrarian quality:
  - `value_inflection_score`
  - `cashflow_inflection_under_loss_score`
  - `fundamental_turnaround_acceleration_score`
  - `h1_oversold_value_score`, if present

Rules:

- Minimum sample count by state.
- Forward labels are audit-only.
- No state-specific threshold fitting after looking at returns.

Outputs:

- `outputs/state_conditional_ic_audit/summary.json`
- `outputs/state_conditional_ic_audit/ic_by_state_and_feature_family.csv`
- `outputs/state_conditional_ic_audit/report.md`

Gate:

- Proceed to R3 only if turnaround/oversold-value IC is materially better than
  momentum IC in CORRECTION/BEAR/RECOVERY with sufficient sample size.
- If momentum plus cash defense is still better, close R2 as negative evidence.

### R3. Gradual Conditional Scoring Tilt

Only allowed if R2 passes.

Rules:

- Default OFF.
- Research-only.
- Maximum 30% of score weight shifted from momentum to turnaround/quality
  features in CORRECTION/BEAR only.
- Two-month hysteresis for state changes.
- Cash policy unchanged.
- No binary regime switch.
- No loser-buying without inflection/quality confirmation.

Gate:

- Broker-ledger A/B only after fixed-book screen.
- OOS non-collapse.
- MDD non-worse unless explicitly classified as a CAGR-only research candidate.
- Effect not one era or one ticker.

### R4. Recovery Breadth-Thrust Re-Entry

Shared with M3. Do not build duplicate logic.

Only allowed if:

- M3 proves material re-entry lag.
- R1/R2 identifies recovery conditions with enough historical examples.

Rules:

- One narrow re-entry rule.
- Fixed-book first.
- No all-in switch.
- No full gross-floor revival.
- Cash defense in stress remains load-bearing.

## Current Market Discussion Rule

Do not label the current market state from narrative alone.

If the user asks "what regime are we in now?", Codex must either:

1. Run R1 using the latest available local data and report coverage, or
2. State that no current-regime claim is justified without refreshing data.

Claude/GPT Pro commentary can inform the framework, but it is not a live market
state measurement.

## Implementation Order

Immediate backlog additions:

1. Create M1/M2/R1/R2 tool stubs and smoke tests only when the current
   Concentrated replacement-quality track is parked or done.
2. Add R1 output to W7 backend alerting after it exists.
3. Defer M3/M4/R3/R4 until audit gates are satisfied.

Suggested future tools:

- `tools/run_momentum_beta_decomposition.py`
- `tools/run_rs_horizon_ic_audit.py`
- `tools/run_reentry_lag_audit.py`
- `tools/run_asymmetric_vol_brake_ab.py`
- `tools/run_regime_nowcast_dial.py`
- `tools/run_state_conditional_ic_audit.py`

Suggested smokes:

- `tests/momentum_beta_decomposition_smoke.py`
- `tests/rs_horizon_ic_audit_smoke.py`
- `tests/reentry_lag_audit_smoke.py`
- `tests/regime_nowcast_dial_smoke.py`
- `tests/state_conditional_ic_audit_smoke.py`

## Review Packet Format

When M/R outputs exist, send a single packet to external review:

- M1 factor exposure table.
- M2 RS horizon IC table.
- R1 state history and signal coverage table.
- R2 IC by state and family.
- Any proposed hook must include:
  - gate pass values
  - applied-count expectation
  - OOS/IS split
  - era/ticker concentration
  - why it is not reviving a falsified lever

Do not ask Claude/GPT Pro for another abstract opinion until at least M1/M2/R1
or R2 produces concrete outputs.

