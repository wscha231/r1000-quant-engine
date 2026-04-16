# Implementation Proposal: Growth-Offense / Defense Architecture

**Target files**
- `r1000_top30_institutional.py`
- `r1000_data_collector.py`
- `colab_run.ipynb`

**Objective**
- Market change should be detected quickly.
- Temporary pullbacks and noisy macro flips should be ignored as much as possible.
- The system should compound hard in strong markets, de-risk earlier in real stress, and improve early-growth entry quality without relying on expensive external reasoning.

**Audience**
- Implementation agent that will write code after this review.
- This document is architecture-first. It defines what to build, in what order, and what to measure before and after each change.

---

## 1. Current Structure Summary

The current engine already has a solid base.

### What is already working
- Multi-layer regime features exist:
  - macro liquidity / stress / inflation / breadth / sector participation
  - event regime features
  - benchmark-relative features
- Adaptive portfolio controls already exist:
  - `compute_regime_portfolio_controls()`
  - `compute_portfolio_sleeve_policy()`
  - `infer_rebalance_interval_policy()`
- Three sleeves already exist:
  - `core_compounder`
  - `future_winner`
  - `early_scout`
- Early growth logic already includes:
  - anticipatory growth
  - inflection / turnaround
  - relative strength
  - Minervini-like momentum checks
  - sparse-history penalty
  - growth floor preservation
- Standalone sleeve backtests and sleeve policy comparisons already exist.

### Current structural limits
- Regime detection is rich, but it is still mostly monthly and median-based.
- Fast market change and false-signal filtering are not clearly separated.
- `early_scout` is directionally correct but too conservative to hold enough weight in many runs.
- Risk defense exists through cash targets and partial stop-loss, but not as an explicit multi-speed overlay.
- The engine still lacks a clean “pullback vs breakdown” distinction.

---

## 2. Design Goal

The target state is not “more signals”.

The target state is:
- faster reaction to real regime changes,
- slower reaction to fake moves,
- stronger offense only when leadership and market structure agree,
- earlier entry into emerging winners with small size first, then scale only after confirmation,
- measurable post-run diagnostics so expensive model review is rarely needed.

This should be built as a **layered state machine**, not as more ad hoc score terms.

---

## 3. Recommended Architecture

Use five explicit layers.

### Layer A. Regime Sensing
- Split regime sensing into:
  - `slow_regime_state`
  - `fast_risk_state`
  - `confirmation_state`

### Layer B. Opportunity Sensing
- Separate stock selection into:
  - durable leader selection
  - emerging winner selection
  - early inflection detection

### Layer C. Portfolio Policy
- Translate regime + opportunity states into:
  - sleeve weights
  - target stock count
  - rebalance cadence
  - name caps
  - cash floor

### Layer D. Risk Overlay
- Keep a monthly-safe path inside current backtest.
- Add a future daily live overlay path later for true fast defense.

### Layer E. Monitoring / Auto-Tuning
- Track hit-rate, false-positive rate, post-entry drift, promotion / demotion, and regime flip quality.
- Use those diagnostics to tune rules directly, instead of requiring a premium model to interpret every run.

---

## 4. Core Additions Before Coding

These are the additions that should be made before the current defensive proposals are implemented.

### A. Split market state into fast and slow

Current problem:
- The engine mixes structural macro and fast market motion in the same decision layer.
- That makes it harder to react fast without overreacting.

Add two separate state blocks.

#### 1. Slow regime state
Purpose:
- structural backdrop
- business cycle / liquidity / macro pressure

Inputs:
- net liquidity
- M2 / WALCL / RRP / TGA
- HY OAS level / change
- inflation pressure
- labor softening
- yield curve inversion
- sustained breadth deterioration

Outputs:
- `slow_regime_state` in:
  - `structural_growth`
  - `balanced`
  - `late_cycle`
  - `stress`
  - `crisis`

Rules:
- Use persistence.
- Require 2-3 monthly confirmations for full state changes.
- This layer should move slowly.

#### 2. Fast risk state
Purpose:
- detect rapid deterioration or rapid re-risking

Inputs:
- VIX level and short-term change
- breadth thrust / breadth collapse
- QQQ vs SPY / SMH vs SPY
- DXY 1m move
- HY OAS change
- benchmark trend breaks
- leadership narrowing jump

Outputs:
- `fast_risk_state` in:
  - `risk_on`
  - `watch`
  - `risk_off`
  - `panic`

Rules:
- This layer may move quickly.
- It should not fully override the slow layer by itself.
- It should only force major de-risking when cross-asset confirmation agrees.

### B. Add a confirmation layer for fake-signal suppression

Current problem:
- The engine can react to stress quickly, but it still lacks an explicit “is this a real regime shift or just a pullback?” block.

Add:
- `regime_confirmation_score`
- `pullback_not_breakdown_score`
- `cross_asset_confirmation_score`
- `regime_disagreement_score`

#### pullback_not_breakdown_score
This should explicitly identify healthy corrections.

Bullish pullback conditions:
- benchmark above 200dma
- breadth weak but not collapsing
- sector participation still moderate
- HY OAS not widening materially
- VIX elevated but below panic
- leaders still holding 50dma / RS leadership
- down move happened on contracting volume or after overextension

If these conditions hold:
- do not let fast risk state push the portfolio fully risk-off
- reduce churn
- keep future / early sleeves from being zeroed too early

#### cross_asset_confirmation_score
Bearish confirmation should require agreement from multiple families:
- equities
- credit
- rates
- dollar
- gold / commodities

Bullish confirmation should also require agreement:
- breadth improving
- participation broadening
- credit tightening
- semis / tech leadership stable
- dollar not spiking

This is the key to “react fast but ignore noise”.

### C. Replace binary regime flips with a transition state machine

Current problem:
- A monthly label can flip too abruptly.

Add explicit transition states:
- `risk_on_confirmed`
- `risk_on_watch`
- `balanced`
- `risk_off_watch`
- `risk_off_confirmed`
- `panic`

Policy:
- sleeve shifts should be smaller in watch states
- cash floors should rise sharply only in confirmed states
- rebalance frequency should tighten in watch / panic states

This will reduce whipsaw materially.

---

## 5. Early Growth / Initial Winner Entry Improvements

This is the most important offense-side section.

The current `early_scout` logic is not wrong. It is just too compressed:
- early signal generation,
- sleeve classification,
- risk penalty,
- sizing,
- and promotion
are all happening in one path.

That should be split into a **three-step life-cycle model**.

### A. Define three growth stages explicitly

Do not rely only on sleeve label. Track a lifecycle stage.

#### Stage 1. `onset_candidate`
Characteristics:
- revenue acceleration or re-acceleration
- OCF / EBITDA / gross profit / operating leverage inflection
- improving RS
- volume accumulation
- analyst or estimate improvement if available
- still incomplete history or unstable profitability allowed

This is the “small starter position” bucket.

#### Stage 2. `early_confirmed`
Characteristics:
- onset signal persists 1-2 rebalances
- price confirms with trend template / breakout quality / RS
- fundamental confirmation improves
- market backdrop remains constructive

This is where size can increase.

#### Stage 3. `emerging_leader`
Characteristics:
- strong multi-quarter confirmation
- high RS persistence
- stable margins / cash flow / revisions
- can be promoted into `future_winner`

This reduces the current need to choose too early between `early_scout` and `future_winner`.

### B. Add better early-growth feature families

The biggest missing offense-side improvement is not “more macro”.
It is better early business inflection detection.

Add these feature groups.

#### 1. Profit / cash inflection block
Prioritize change, not absolute quality.

Add or strengthen:
- `ocf_turn_positive_score`
- `ebitda_turn_positive_score`
- `gross_profit_turn_positive_score`
- `gross_margin_inflection_score`
- `operating_margin_inflection_score`
- `operating_leverage_score`
- `fcf_directional_improvement_score`

Important rule:
- For early growth, a company moving from bad to less bad can matter more than one that is already “good”.
- That means delta and persistence matter more than level.

#### 2. Revenue thrust block
Add explicit reward for recent acceleration:
- 2-quarter revenue acceleration
- 4-quarter revenue trend slope
- acceleration vs sector median
- acceleration with stable share count

Use:
- reward recent acceleration
- penalize fake acceleration driven by one-off low base without follow-through

#### 3. Institutional accumulation proxy block
Because free data is limited, use price / volume proxies:
- relative dollar volume surge
- up-volume / down-volume balance
- OBV trend
- earnings gap follow-through
- accumulation-day count over 8 weeks
- pullback volume contraction
- breakout retest hold quality

These features are often more useful than expensive narrative reasoning for early leaders.

#### 4. Theme / family leadership block
A lot of big winners come from leading clusters.

Add:
- theme-relative strength score
- subgroup leadership rank
- second-derivative leader score

Examples:
- semis
- AI infra
- power / electrical
- data center / optics
- defense
- select energy / resources

Objective:
- prefer the next leader inside a strong group over random isolated names.

### C. Early entry timing should be staged, not binary

Do not force early growth into full selection immediately.

Add a staged entry policy:
- first entry:
  - small size
  - only if early-onset and market backdrop not hostile
- second entry:
  - only after confirmation persistence
- promotion:
  - only after score persistence plus market confirmation

This is better than only loosening caps.

### D. Add “too extended to start” filter

Current risk:
- high-momentum growth can be bought too late.

For new early entries:
- penalize names that are too far above 50dma unless:
  - earnings gap breakout,
  - strong 3-week-tight type consolidation,
  - or pullback-hold structure is present

This prevents chasing while still allowing legitimate strength.

### E. Add “pullback quality” feature

This is a missing but very important feature.

For strong growth names:
- reward:
  - shallow pullbacks
  - declining down-volume
  - support near 21/50dma
  - RS staying high during pullback
- penalize:
  - high-volume breakdown
  - repeated failed breakouts
  - sharp underperformance during market weakness

This helps buy leaders on resets instead of only on breakout day.

---

## 6. Portfolio Construction Improvements

### A. Move from static sleeve weights to bounded policy ranges

Do not hard-code one “correct” base split.

Keep:
- base sleeve targets

Add:
- bounded regime ranges

Example policy framework:
- `core_compounder`
  - 0.15 to 0.65
- `future_winner`
  - 0.20 to 0.70
- `early_scout`
  - 0.00 to 0.45
- cash
  - 0.00 to 0.60

Then determine actual targets from:
- slow regime state
- fast risk state
- cross-asset confirmation
- early candidate share
- regime disagreement score

This is better than manually debating 30/40/15 repeatedly.

### B. Use stage-based caps, not only sleeve-based caps

Within growth sleeves, cap by stage:
- onset candidate:
  - very small starter
- early confirmed:
  - medium cap
- emerging leader:
  - highest cap

This aligns size with evidence quality.

### C. Let target stock count depend on breadth and confidence

Current dynamic stock count is directionally good.
Improve it by incorporating:
- regime disagreement score
- median selection confidence
- concentration of top-ranked opportunities
- breadth / participation

Policy:
- broad healthy market + many good names:
  - more names
- narrow market + few real leaders:
  - fewer names

### D. Separate defense overlay from selection engine

Important architecture rule:
- stock selection engine should answer:
  - “what are the best names?”
- defense overlay should answer:
  - “how much gross exposure is appropriate now?”

Do not bury everything inside stock ranking.

This makes the system easier to tune without expensive reasoning.

---

## 7. Risk Overlay Design

This should be split into monthly-safe and future daily overlay.

### A. Monthly-safe overlay
Can be backtested honestly in current structure.

Add:
- sleeve-specific stop-loss
- yield curve stress discount
- cross-asset confirmation
- regime smoothing
- pullback-not-breakdown suppression

### B. Daily live overlay
Should be designed now, even if implemented later.

Add later as a separate module:
- VIX hard guard
- portfolio drawdown circuit breaker
- realized vol targeting
- emergency de-risking when fast risk state is `panic`

Important:
- daily live overlay should not be backtest-claimed as if monthly engine proved it.
- report it separately.

---

## 8. False Signal Suppression Rules

These are the concrete rules that should be added before aggressive offense changes.

### A. Do not full de-risk on a pullback if all are true
- benchmark trend still positive
- breadth > panic threshold
- credit not widening sharply
- leadership group still intact
- pullback_not_breakdown_score high

### B. Do not expand early sleeve unless all are true
- growth signal constructive
- early candidate share non-trivial
- cross-asset bearish confirmation low
- market participation not collapsing

### C. Do not promote early -> future unless persistence holds
- score persists across 2 rebalances
- technical damage absent
- business inflection not reversing

### D. Do not demote too aggressively on a one-month wobble
- use persistence windows
- use disagreement score
- use confirmation thresholds

---

## 9. Metrics That Must Be Added Before Further Tuning

Without these, the team will keep guessing and paying for high-cost reasoning.

Add these reports.

### A. Regime quality report
- regime flips per year
- average duration per regime
- panic false-positive count
- cross-asset confirmation hit rate
- pullback-not-breakdown save count

### B. Sleeve funnel report
- raw early candidate count
- final early selected count
- early candidate share
- early target weight
- early realized weight
- early zero-weight months
- reasons for early suppression

### C. Lifecycle report
- onset_candidate -> early_confirmed conversion rate
- early_confirmed -> future_winner promotion rate
- failed onset rate
- average return after promotion

### D. Post-entry return diagnostics
For each sleeve and stage:
- 1m / 3m / 6m / 12m forward hit rate
- median return
- tail loss
- contribution to total CAGR
- contribution to max drawdown

### E. Pullback vs breakdown diagnostics
- count of names saved by pullback suppression
- return difference between “held through pullback” vs “would have sold”

These diagnostics will reduce the need for Opus because the engine will explain its own behavior.

---

## 10. Recommended Implementation Order

This is the order another coding agent should follow.

### Phase A. Measurement first
- Add regime quality diagnostics
- Add sleeve funnel diagnostics
- Add lifecycle transition diagnostics
- Add reasons-for-suppression columns for `early_scout`

### Phase B. Signal-quality improvements
- Add yield curve features
- Add cross-asset confirmation score
- Add pullback-not-breakdown score
- Add regime smoothing / watch states

### Phase C. Early-growth offense improvements
- Add inflection feature block
- Add institutional accumulation proxies
- Add stage-based lifecycle labels
- Add staged entry / promotion logic

### Phase D. Portfolio policy improvements
- Map slow regime + fast risk + confirmation into bounded sleeve ranges
- Add stage-based caps
- update target stock count with confidence / disagreement

### Phase E. Risk overlay
- Monthly-safe stop-loss extension first
- Daily overlay design second

---

## 11. What Not To Do

Do not:
- keep stacking more score terms into one flat formula without state separation
- claim intramonth defense improvements using monthly-only backtests
- widen early caps before measuring why early exposure is being suppressed
- use expensive external reasoning for routine tuning that should be report-driven
- turn every macro input into a direct allocation switch

---

## 12. Cost-Efficient Operating Model

The system should be designed so expensive model review is rare.

### Use cheap/default models for
- code changes
- threshold tuning from diagnostic tables
- notebook/report updates
- backtest comparison summaries
- feature ablation

### Escalate to expensive reasoning only when one of these triggers fires
- regime disagreement score remains high for 2+ runs
- top portfolio names change drastically without a large market-state shift
- early_scout hit rate improves but drawdown explodes
- cross-asset and slow regime disagree repeatedly
- validation metrics deteriorate without obvious data-coverage cause

If the above diagnostics are built, premium reasoning becomes an exception path, not a standard tool.

---

## 13. Final Recommendation

The highest-value next move is not another broad “alpha term”.

It is this sequence:

1. make market-state transitions explicit,
2. add fake-signal suppression,
3. add lifecycle-aware early-growth selection,
4. separate offense sizing from defense overlay,
5. add diagnostics so the system explains itself.

That structure will do more for long-run CAGR / drawdown than continuing to hand-tune sleeve weights in isolation.
