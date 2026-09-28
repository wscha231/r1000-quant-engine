# Concentrated Cash-Funded Early Entry Result - 2026-06-29

## Verdict

`future_winner_scout_score_add7` is the first cheap broker-ledger Concentrated candidate found in this round that crosses the mission line:

| Arm | CAGR | MaxDD | Sharpe | Avg cash | Events |
| --- | ---: | ---: | ---: | ---: | ---: |
| official baseline | 47.20% | -25.82% | 1.440 | 42.14% | n/a |
| future_winner_scout_score_add7 | 50.36% | -24.84% | 1.461 | 36.97% | 84 |

This is research-only evidence, not production promotion. `pit_universe_label_clean=false` remains a production blocker.

## What Changed

The harness funds one small early-entry position from existing Concentrated cash at each monthly rebalance:

- It does not sell or replace existing holdings.
- It does not force gross exposure above available cash.
- It selects the highest-ranked unheld candidate by a PIT signal for that rebalance date.
- It skips crisis/defense rows by default.
- It measures with `broker_ledger_next_close`, integer shares, 25 bps cost, and max fill lag 7.

This differs from the rejected broad gross-floor test. Gross-floor forced more cash into the existing book and worsened both CAGR and MDD. This harness only deploys cash when a candidate-level future-winner signal exists.

## Refined Sweep

Output:

`artifacts/28074476465/concentrated_cashfunded_early_entry_refined_20260629/summary.json`

Passing candidate:

```json
{
  "arm": "future_winner_scout_score_add7",
  "signal": "future_winner_scout_score",
  "add_weight": 0.07,
  "event_count": 84,
  "cagr": 0.5036394647116971,
  "max_dd": -0.24835536446335538,
  "sharpe": 1.4610234309122887,
  "avg_cash": 0.36970510019992686,
  "trade_count": 723,
  "oos_cagr": 1.33656062397931,
  "oos_mdd": -0.24835536446335538,
  "oos2_cagr": 0.9594195084170969,
  "oos2_mdd": -0.24835536446335538
}
```

Near misses:

- `future_winner_scout_score_add6`: 49.97% / -24.61%
- `future_winner_scout_score_add8`: 50.79% / -25.10%
- `breakout_setup_quality_score_add9`: 50.80% / -25.49%
- `portfolio_future_winner_engine_score_add6`: 50.56% / -27.49%

The 7% future-winner-scout arm is the cleanest current tradeoff.

## Caveats

- This is a generated target-book A/B, not a full policy replay.
- The signal must be verified as PIT-safe in the full replay path before any fullrun.
- `future_winner_scout_score` is treated as a PIT composite feature, not a forward-return label. The harness now blocks explicit forward/audit-label columns such as `period_forward_return` from being used as selection signals.
- This adds 84 monthly early-entry events and raises trade count from about 602 to 723, so turnover/cost sensitivity must be checked.
- The candidate uses the current clean7Y artifact. PIT universe is still not production-clean.
- Fullrun should wait until the default-OFF policy hook reproduces the same target-book changes and broker result.

## What We Should Salvage From Rejected Paths

The rejected paths still contain useful side lessons:

- Broad gross-floor failed as a policy lever, but it confirmed the cash problem is not "deploy all idle cash." Deployment needs candidate-level confirmation.
- Score-sizing failed under cap-safe broker evidence, but it is still useful as telemetry for identifying which selected names the engine most wants to own. Do not use it to override the cap until a separate capped broker A/B passes.
- Weekly leader trading failed as a direct trading policy because turnover and drawdown exploded. Keep weekly leader and 2-week RS as watchlist/review telemetry, not automatic position churn.
- AI Capex tilt passed cheap screens but failed broker evidence for Concentrated. Keep the ontology and revision/bottleneck telemetry; do not assume theme labels create broker alpha.
- Whipsaw/hold-duration diagnostics remain useful for explaining missed compounding, but broad hold rescue was rejected. Any hold extension must be narrow and thesis-confirmed.

## 2-Week RS Decision

Do not add 2-week RS directly to the score yet.

The incumbent/challenger 2-week RS audit showed that direct scoring looked acceptable in-sample but failed OOS. The right use is:

- persist `weekly_rs_2w` as telemetry,
- use it to explain leader acceleration/deceleration in reports,
- use it as a secondary condition only after a separate OOS-stable screen passes,
- avoid using it as a standalone buy/sell/replacement score.

This keeps the system responsive to fast leadership changes without overfitting a short-horizon momentum signal.

## Next Implementation Step

Design a default-OFF hook:

`PHASE_CONCENTRATED_CASHFUNDED_EARLY_ENTRY_ENABLED=1`

Suggested default arm:

- signal: `future_winner_scout_score`
- add weight: `0.07`
- funding source: existing cash only
- portfolio: Concentrated only
- crisis/defense deployment: off
- no ticker/sector/date hardcoding
- no existing holding replacement

Acceptance before fullrun:

- `applied_event_count > 0`
- generated target book matches this harness within tolerance
- broker-ledger replay stays near or above 50% CAGR and -25% MDD
- OOS does not collapse
- no future-return columns used in selection
- signal provenance audit confirms all selected columns are available at `rebalance_date`
- production remains blocked while PIT universe is unclean
