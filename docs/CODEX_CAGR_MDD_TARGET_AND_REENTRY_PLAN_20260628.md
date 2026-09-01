# AlphaOps vNext CAGR/MDD Target Plan - Re-Entry Timing Track

## Fixed Targets

Use clean 7Y `broker_ledger_next_close` only.

| Portfolio | Target CAGR | Target MaxDD | Clean 7Y baseline | Gap |
|---|---:|---:|---:|---:|
| Main | >= 35.00% | >= -25.00% | 33.15% / -26.02% | +1.85pp CAGR, +1.02pp MDD |
| Concentrated | >= 50.00% | >= -25.00% | 46.24% / -25.82% | +3.76pp CAGR, +0.82pp MDD |

Production promotion remains blocked while `pit_universe_label_clean=false`.
Any pass before PIT clean is `research_7y` evidence only.

## Current Evidence

Recent tested candidates:

| Candidate | Result | Decision |
|---|---|---|
| Concentrated score sizing, cap-safe | Did not close gap | reject as policy candidate |
| Broad gross-floor / broad exposure | MDD risk / broad failure | reject |
| Broad hold-duration rescue | negative or no durable edge | reject |
| Broad earnings-confirmed hold hook | CAGR fell to 45.22%, MaxDD worsened to -27.51% | reject |
| Replacement-quality incumbent protection | screen candidates had negative mean forward edge | reject/inconclusive |

What remains true:

- Whipsaw cost is material.
- Stock selection is often early enough to identify leaders.
- The failed fixes show that "hold everything longer" is not the answer.

## Surviving Hypothesis

The next method should target the second half of the whipsaw:

> If the system sells a future leader, re-enter earlier when a PIT daily signal
> says the leader has reclaimed strength, instead of waiting until the monthly
> policy buys it much higher.

This is different from broad hold protection:

- It does not force the system to keep every incumbent.
- It waits for observable post-exit recovery.
- It can be implemented as a daily/weekly re-entry alert or re-entry candidate,
  then measured by broker replay.

## Quick Diagnostic

Using `artifacts/28074476465/whipsaw_cost_audit_20260628/concentrated_events.csv`
and `artifacts/28074476465/cache_prices`, only positive premium sell/rebuy
events with `rebuy_premium > 10%` were sampled.

Daily PIT triggers were tested after a 3-trading-day cooldown:

| Trigger | Events | Positive saved-premium rate | Avg saved premium | Median days earlier |
|---|---:|---:|---:|---:|
| reclaim sell price +5% | 53 | 94.3% | 25.8% | 25.0 |
| reclaim sell price +10% | 50 | 92.0% | 21.9% | 24.0 |
| reclaim sell price +15% | 45 | 82.2% | 19.7% | 23.0 |
| rebound 8% from post-sell trough | 52 | 92.3% | 29.5% | 21.5 |

Interpretation:

- Re-entry delay is a real candidate source of CAGR recovery.
- This is still an outcome-selected diagnostic because it looks at known
  sell/rebuy whipsaws.
- It is not yet broker evidence and must not be used as a live rule.

## Required Next Screen

Create a measurement-only tool:

- `tools/run_reentry_timing_whipsaw_screen.py`

Scope:

1. Use every sell event, not only successful future rebuys.
2. Build daily PIT trigger candidates after the sell date:
   - cooldown >= 3 trading days
   - reclaim sell price +5% / +10%
   - rebound 8% from post-sell trough
   - optional: close above 20-day high after cooldown
3. Record whether the ticker was later actually re-entered and at what premium.
4. Measure false positives:
   - trigger fired but future 20/63d return was negative
   - trigger fired during crisis/defense state
   - trigger fired while ticker remained below MA200
5. Rank triggers by:
   - saved premium on true whipsaws
   - false positive rate on all sells
   - drawdown after trigger
   - median days earlier than official re-entry

Forward returns are audit labels only. Trigger selection must use price path and
PIT state available at the trigger date.

## Acceptance Gate

Do not design a hook unless the screen passes all of these:

- trigger_count >= 20
- true whipsaw saved-premium positive rate >= 60%
- false-positive 20d loss rate <= 45%
- median saved premium >= 5%
- no crisis/defense trigger dominance
- candidate is implementable without hardcoded tickers/dates/sectors

If the screen passes, then design a default-OFF re-entry candidate hook:

- Concentrated first
- daily/weekly review-only candidate, not automatic live trade
- broker A/B before fullrun
- accept only if Concentrated CAGR improves by >= +0.50pp and MaxDD does not
  worsen

If it fails, discard this direction and move to separate structural levers:

- PIT-clean universe track
- concentrated sizing with risk cap redesign
- Main market-heat MDD defense

## Fullrun Rule

No fullrun for this track until:

1. screen passes,
2. default-OFF hook has `applied_count > 0`,
3. cheap broker replay improves Concentrated CAGR and does not worsen MDD.

Production promotion remains forbidden until PIT membership is clean.
