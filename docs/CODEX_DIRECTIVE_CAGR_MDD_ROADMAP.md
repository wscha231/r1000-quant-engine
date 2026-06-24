# Codex Directive: CAGR/MDD Target Roadmap

Version: v1  
Date: 2026-06-24  
Status: working roadmap, not a production-promotion decision

## Current State

This roadmap converts the long-term objective into gap-driven engineering work.
It is not a single implementation task. Each phase must pass its gate before the
next phase is treated as valid evidence.

Current known context:

- Clean 7Y full rebuild run `28074476465` is still running on `master`.
- PR #151, `feat: add leadership persistence hold gate`, is open as a draft
  experiment hook and has green CI.
- PR #151 is default OFF and must not be treated as production activation.
- `pit_universe_label_clean=false` continues to block production promotion even
  if research CAGR/MDD targets are met.
- All performance decisions must use `broker_ledger_next_close` mechanics only.

Forbidden unless separately approved:

- production promotion
- live trading
- T3/recovery work
- proxy 8Y/10Y work
- legacy/proxy/weight-level metrics as promotion evidence
- future labels or forward returns in ranking

## 0. North Star

| Sleeve | CAGR Target | MDD Target | Current Research Approx. | Remaining Gap |
| --- | ---: | ---: | ---: | --- |
| Main | >= 35% | >= -25% | ~35.0% / -26.0% | MDD needs about +1.0pp |
| Concentrated | >= 50% | >= -25% | ~46.0% / -24.6% | CAGR needs about +4.0pp |

The bottleneck is different by sleeve:

- Main is primarily an MDD problem. CAGR is near or above target, but drawdown is
  about 1pp too deep.
- Concentrated is primarily a CAGR problem. MDD is near or inside target, but
  return is about 4pp short.

Therefore, do not apply one cash policy to both sleeves. More cash is likely
harmful to Concentrated CAGR unless it demonstrably reduces idiosyncratic MDD.

## Right-Tail Skill Policy

Concentrated growth strategies normally earn a large share of returns from a
small number of winners. Do not reject a result only because it is OOS-heavy or
because the top winners contribute a large share of CAGR. The correct question
is whether those winners were identifiable at the rebalance date using PIT-
visible information.

High OOS/IS ratios, top-winner concentration, or leave-top-winner sensitivity
are audit triggers, not automatic rejection rules.

Skill-vs-luck audit:

1. **Ex-ante explainability**
   - At each winner's entry rebalance date, the selected name should rank highly
     on PIT-visible signals: relative strength, theme leadership, price/volume
     thrust, earnings/revision/event reaction, Form4/13F/ETF support, and
     liquidity.

2. **Cross-era repetition**
   - Winners should appear across multiple eras or themes, not only in one lucky
     episode.

3. **Era-level leave-best-out**
   - Removing the best name inside each era is a fair robustness check.
   - Removing the single best name across the whole seven-year concentrated book
     is not a fair hard-reject rule by itself, because a concentrated book is
     designed to monetize right-tail winners.

4. **Factor-adjusted residual alpha**
   - Regress results against SPY, QQQ, SMH/SOXX, and broad size/value/momentum
     factors where available.
   - The winner contribution should include positive residual alpha, not only
     benchmark or semiconductor beta.

5. **Walk-forward robustness**
   - The same direction should hold across walk-forward folds and, if available,
     proxy robustness evidence.

Required diagnostic fields or report rows:

- `winner_capture_rate`
- `early_entry_score`
- `hold_winner_score`
- `premature_sell_loss`
- `top_1_winner_contribution`
- `top_3_winner_contribution`
- `top_5_winner_contribution`
- `era_leave_best_out_cagr`
- `factor_adjusted_winner_alpha`
- `theme_leader_capture`

Decision rule:

- If OOS/IS is high or top-winner concentration is high, run this audit.
- If the audit passes, classify the result as right-tail skill and allow it to
  proceed as research evidence.
- If the audit fails, reject it as luck or overfit.

This audit is an acceptance and interpretation layer. It is not itself a CAGR or
MDD improvement lever.

## 1. Gap To Lever Map

### Concentrated CAGR Gap

Priority order:

1. **Lever #3: Regime-Conditional Gross Floor**
   - Problem: green-regime idle cash is a large CAGR drag.
   - Mechanism: increase gross exposure only in confirmed GREEN or strong-breadth
     regimes.
   - Expected impact: +1pp to +3pp CAGR if 2022-style defense cash is preserved.

2. **Lever #1: Leadership-Persistence Hold**
   - Existing PR: #151.
   - Problem: healthy leaders may be replaced too early.
   - Mechanism: a healthy prior leader requires a stronger challenger score gap
     before replacement.
   - Expected impact: +0.5pp to +1.5pp CAGR if premature EXIT_REPLACE leakage is
     real and the lever actually fires.

3. **Lever #4/#5: Capture And Candidate-Gate Calibration**
   - Problem: new leaders may enter too late or be blocked by overly strict
     gates.
   - Mechanism: shorten PIT-visible leader promotion latency without increasing
     false entries.
   - Expected impact: closes residual Concentrated CAGR gap.

Priority interpretation:

- Expected impact priority: Lever #3 may be the largest Concentrated CAGR lever.
- Execution safety priority: Lever #1 runs first because it does not increase
  gross exposure and is less likely to worsen MDD.
- Do not let the safer first experiment delay the gross-floor work indefinitely;
  measure Lever #3 next after Lever #1 wiring is proven.

### Main MDD Gap

Priority order:

1. **Lever #2: Asymmetric Exit**
   - Winner: trailing stop, hold through normal shakeouts.
   - Loser: faster hard cut.
   - Keep existing WARNING/TRIM technical sell behavior when it is proven useful.
   - Expected impact: +1pp to +2pp MDD improvement with <= 0.5pp CAGR loss.

2. **Lever #6: Market-Heat Cash, Main Only**
   - Do not use CNN Fear & Greed as backtest evidence; it is live/context only
     unless PIT history exists.
   - PIT inputs only: VIX z-score, breadth, index distance to 200dma, index RSI,
     net liquidity, credit.
   - Greed alone must not trigger cash. Require at least two independent warning
     families, such as heat high plus breadth weakening or trend break.

Keep intact:

- crisis/VIX/breadth defensive cash that worked in 2022
- WARNING/TRIM technical risk exits with proven forward-loss avoidance

## 2. Phase Roadmap

### Phase 0: Data Baseline

This is time-boxed. It is not alpha work.

1. Clean 7Y window:
   - Cheap preflight must pass before a fullrun.
   - Expected first decision: `2019-05-31`.
   - Expected first next-close fill: `2019-06-03`.
   - Expected years: `[7.00, 7.05]`.
   - Fullrun attempts are limited. If repeated attempts fail, classify as
     `research_7y_tolerance` and proceed with A/B as research only. Continue to
     block production promotion.

2. Concentrated trading-day count:
   - Fix or validate that `run_account_evaluation.py` uses calendar trading-day
     coverage, not only observed equity-curve row count.
   - Cash-only days must not make Concentrated look like a shorter window.
   - Both Main and Concentrated must report calendar trading-day coverage.
   - Gate on `calendar_trading_day_count`, not observed equity rows.
   - Output must distinguish:
     - `equity_curve_observed_day_count`
     - `calendar_trading_day_count`
   - Required projection before another expensive fullrun:
     - Main `calendar_trading_day_count >= 1764`
     - Concentrated `calendar_trading_day_count >= 1764`

Phase 0 gate:

- both sleeves have valid window or explicit tolerance label
- both sleeves have calendar trading-day coverage or explicit tolerance label
- `ready_for_policy_replay=true`
- future `available_from` leakage is zero
- no production-promotion claim if PIT universe membership is not clean

### Phase A: Close Concentrated CAGR Gap

1. A1: Run Lever #1 A/B from PR #151.
   - `PHASE_LEADERSHIP_PERSISTENCE_HOLD_ENABLED=1`
   - shadow or experiment path only
   - no production mutation

2. A2: Design and measure Lever #3.
   - Gross floor applies only when `crisis_state == GREEN` and breadth/regime is
     confirmed strong.
   - WATCH/DEFENSE/CRISIS cash defense must remain alive.
   - Suggested grid: `R1000_CONC_GROSS_CAP_FLOOR` in `{0.0, 0.7, 0.8, 0.9}`.

3. A3: Combine winners from A1 and A2.
   - Check interaction regression.

Phase A gate:

- Concentrated CAGR >= 50%
- Concentrated MDD >= -25%
- `theme_leader_capture` does not regress
- high OOS/IS or top-winner concentration triggers the right-tail skill audit
  above; it is not an automatic reject by itself

### Phase B: Close Main MDD Gap

1. B1: Lever #2 daily-stop / trailing-stop grid.
   - Use broker-ledger replay only.
   - Preserve winner upside.
   - Cut weak names faster.

2. B2: Lever #6 market-heat cash, Main only.
   - PIT inputs only.
   - No live-only Fear & Greed as backtest evidence.
   - This should be integrated with the regime-to-gross-exposure curve rather
     than fighting Lever #3.

Phase B gate:

- Main MDD >= -25%
- Main CAGR >= 35%
- Main CAGR loss <= 0.5pp versus baseline

### Phase C: Integration And Robustness

Run one combined fullrun only after cheap checks and smaller lever measurements
are green.

Acceptance:

- Main CAGR >= 35% and MDD >= -25%
- Concentrated CAGR >= 50% and MDD >= -25%
- all common ship gates pass
- leakage is zero
- no single ticker or single era explains the improvement
- production promotion remains blocked until PIT universe evidence is clean or
  the user approves an alternative evidence contract

## 3. Lever Specifications

### Lever #1: Leadership-Persistence Hold

Existing draft PR: #151.

Environment:

- `PHASE_LEADERSHIP_PERSISTENCE_HOLD_ENABLED=1`

Mechanism:

- Protect only healthy prior leaders:
  - `holding_state == HOLD`
  - `hold_replace_decision == keep_prior_holding`
  - prior weight above floor
  - allowed `leader_tier`
  - trend alive
- Do not protect `WARNING`, `TRIM`, broken, hard-rejected, or cash positions.

Hard gates before using results:

- output rows with `leadership_persistence_hold_applied=True` must be greater
  than zero, otherwise it is a wiring no-op
- `theme_leader_capture` must not regress
- `entry_exit_timing_audit` should show:
  - EXIT_REPLACE 126d excess moving toward <= 0
  - `pct_held_365d_plus` increasing
  - no unacceptable MDD degradation

Lean A/B sequence:

1. **A/B v1**
   - Test one conservative threshold first, preferably around `0.75 sigma`.
   - Required checks:
     - applied count > 0
     - `theme_leader_capture` does not regress
     - common ship metrics do not break

2. **A/B v2**
   - Only if v1 fires and shows useful signal.
   - Expand to a grid such as OFF, `0.75 sigma`, `0.85 sigma`, and `1.10 sigma`.
   - Add heavier diagnostics:
     - missed new leader count
     - premature sell loss
     - `pct_held_365d_plus`
     - replacement threshold not met forward 63d/126d audit labels

### Lever #3: Regime-Conditional Gross Floor

Environment:

- `R1000_CONC_GROSS_CAP_FLOOR`
- optional explicit phase gate if needed

Mechanism:

- Raise Concentrated gross only in confirmed GREEN / strong-breadth regimes.
- Do not weaken WATCH/DEFENSE/CRISIS cash defense.

Gate:

- Concentrated delta CAGR >= +1.0pp
- 2022-style defense cash remains effective
- delta MDD >= -1.0pp
- `cash_reentry_quality` shows green idle cash down, not crisis cash down

### Lever #2: Asymmetric Exit

Environment:

- `R1000_DAILY_STOP_*`

Mechanism:

- winners use a trailing stop
- losers use a faster hard stop
- rank-based replacement should not override healthy winner continuation without
  a clear score/technical break

Gate:

- Main MDD improves by at least +1.0pp
- Main CAGR loss is no worse than -0.5pp

### Lever #6: Market-Heat Cash

Scope:

- Main only until proven otherwise.

Allowed PIT inputs:

- VIX z-score
- breadth percentage above MA200
- index distance to MA200
- index RSI
- net liquidity / credit

Forbidden:

- live-only CNN Fear & Greed as historical evidence
- greed-only cash triggers
- ticker/date/era-specific thresholds

Gate:

- Main MDD improves by at least +1.0pp
- Main CAGR loss is no worse than -0.5pp
- walk-forward evidence shows the rule is not fitted only to 2020 or 2022

### Lever #4/#5: Capture And Candidate-Gate Calibration

Mechanism:

- reduce new-leader promotion latency
- calibrate candidate gates when PIT-visible RS, volume thrust, and theme
  rotation are strong

Gate:

- `theme_leader_capture` improves
- false re-entry does not increase materially
- no forward-return leakage

## 4. Measurement Protocol

Use cheap measurement before expensive fullruns:

- lever-sweep or focused replay first
- fullrun only after preflight and cheap evidence are green

Official metrics:

- `broker_ledger_next_close` only
- integer shares
- next-close fills
- cash ledger
- fees
- daily account MDD

Common ship gate:

- delta CAGR >= +0.5pp
- delta Sharpe >= -0.05
- delta MDD >= -3pp
- `early_scout >= 4`
- `theme_leader_capture` does not regress
- high OOS/IS or winner concentration triggers the right-tail skill audit
- walk-forward plus 126-day embargo pass

## 5. Decision And Stop Rules

- Each lever must close its assigned gap without breaking the other sleeve.
- If a lever has no `applied=True` evidence, treat it as a wiring failure, not a
  negative result.
- OOS/IS ratio above a nominal goal limit is an audit trigger, not an automatic
  reject for a concentrated right-tail strategy.
- Leave-top-1 or leave-top-3 diagnostics must be interpreted by era; whole-run
  top-winner removal is not a fair standalone hard-reject rule for a five-name
  concentrated book.
- Phase 0 gets a limited number of attempts. If the clean 7Y gate remains stuck,
  classify as `research_7y_tolerance` and continue alpha work as research only.
- Production promotion, live trading, T3/recovery, and proxy 8Y/10Y remain
  forbidden until separately approved.

## 6. Invariant Guardrails

- Every rule must be PIT:
  - decision-time data only
  - `available_from <= rebalance_date`
  - no forward returns in live ranking
- No hardcoded tickers, dates, sectors, or era-specific shortcuts.
- Keep:
  - `future_labels_excluded=true`
  - `used_forward_return_in_ranking=false`
  - OOS lock green
- New features must be wired through:
  - feature-store keep columns
  - hard sanitize
  - phase zero-placeholder handling
- All levers are env-gated and default OFF.

## 7. Roadmap Completion Definition

The roadmap reaches research success when one valid or explicitly tolerance-
labeled run simultaneously satisfies:

- Main CAGR >= 35%
- Main MDD >= -25%
- Concentrated CAGR >= 50%
- Concentrated MDD >= -25%
- common ship gate passes
- generalization gate passes
- leakage is zero

Production promotion remains a separate decision and requires PIT universe
membership evidence or a user-approved alternative evidence contract.
