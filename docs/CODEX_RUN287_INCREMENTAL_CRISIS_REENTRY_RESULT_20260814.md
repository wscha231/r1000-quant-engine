# Run287 incremental crisis-reserve re-entry result

Date: 2026-08-14

Status: research-only challenger implemented; target-level replay passed;
broker-ledger performance verdict blocked by absent price parquet artifacts.

## Change

The prior canonical re-entry arm multiplied the whole normal equity target by
the stage multiplier. That also held back cash that existed before the crisis.
The default-off challenger instead uses:

```text
episode_incremental_crisis_reserve
  = normal_equity_weight - crisis_equity_weight

target_equity_weight
  = crisis_equity_weight
  + reentry_multiplier * episode_incremental_crisis_reserve
```

The existing stage multipliers remain `0.25 / 0.60 / 1.00`. Normal capacity
cash is preserved and only crisis-created Reserve is released. The challenger
is enabled only by `--incremental-crisis-reentry`; operating defaults and
same-close target mutation remain unchanged.

## Bounded replay inputs

- GitHub Actions run: `30682637459`
- Official broker-ledger artifact: `8816483823`
- User operating minimal artifact: `8816480816`
- Source target books: artifact Main and Concentrated operating target books
- Crisis features: artifact `outputs/crisis_signals/daily_features.parquet`
- Mode: `conservative`
- Snapshots: 100 per portfolio
- Broker replay: not run; artifact contained the 517-ticker cache manifest but
  not the underlying parquet price files

## Target-level comparison

| Portfolio | Arm | Mean cash | Re-entry mean cash | Re-entry mean equity | Max cash |
|---|---|---:|---:|---:|---:|
| Main | prior canonical | 36.94% | 46.31% | 53.69% | 85.00% |
| Main | incremental Reserve | 31.79% | 24.85% | 75.15% | 50.00% |
| Concentrated | prior canonical | 35.50% | 42.92% | 57.08% | 75.00% |
| Concentrated | incremental Reserve | 30.35% | 21.46% | 78.54% | 50.00% |

- The two arms had identical state counts.
- Exactly 24 re-entry snapshots changed in each portfolio.
- Cash was lower on all 24 changed snapshots, unchanged on 76, and higher on
  zero snapshots.
- Mean cash declined by 5.15 percentage points in both portfolios.
- The challenger did not alter `CRISIS`, `DEFENSE`, `WATCH`, `GREEN`, or
  `DEGRADED_DATA` target behavior.

## Remaining blocker and next gate

This is not a CAGR/MDD or promotion result. The downloaded official artifacts
do not contain the price parquet cache needed for a reproducible next-close,
integer-share, 25 bps broker replay. The next safe action is to restore the
exact cache through the existing research cache workflow or publish a
hash-verified cache artifact, then run baseline and challenger broker replays
on identical inputs.

The acceptance comparison must include final value from $100,000, CAGR, MDD,
Sharpe, turnover, fees, crisis-window drawdown, recovery lag, and cash drag.
No fullrun, operating target mutation, production/live trading, or automatic
promotion is authorized.

Separately, 53 of 100 snapshots were `DEGRADED_DATA`; that is the next major
cash-drag investigation after the incremental re-entry arm receives a valid
broker-ledger verdict.
