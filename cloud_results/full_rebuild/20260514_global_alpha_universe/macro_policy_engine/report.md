# Macro Policy Engine

Research-only sidecar. It does not change production weights.

- Status: `completed`
- Months: 84
- Latest risk state: `green`
- Latest style state: `breakout_growth`
- Cash-raise confirmations: 0
- Confirmed cash raise: `False`
- Recommended cash floor: 3.0%
- Recommended target N: 12
- Monster exception capacity: 15.0%
- Monster exception allowed: `True`
- Cash-raise gate: `none`
- New-buy policy: `normal`
- Trim policy: `winner_hold_stale_watch`
- Action: `favor_future_winners_and_monster_breakouts`
- Snapshot source: `scored_latest`

## Risk State Counts

- crisis: 5
- green: 46
- recovery: 8
- red: 10
- yellow: 15

## Regime Speed Diagnostics

- balanced_under_drawdown: 10
- late_risk_alert: 11
- possible_cash_drag: 6
- premature_growth_reentry: 1
- unconfirmed_cash_raise: 17

## Interpretation

Use `macro_policy_by_month.csv` to A/B a slower re-entry / faster
defense policy in Main v2. Large cash raises require at least two
independent confirmations from long-trend damage, liquidity stress,
breadth/credit stress, or severe drawdown. Short event shocks alone
should not force broad cash because monster leaders can keep rising.
Use `regime_speed_audit.csv` to find months where the current regime
label returned to balanced too early or kept excessive cash after
risk had already normalized.

Production promotion requires a separate historical challenger replay.

## First Diagnostics

- 2020-01-31: unconfirmed_cash_raise (balanced -> green)
- 2020-09-30: unconfirmed_cash_raise (balanced -> green)
- 2021-08-31: late_risk_alert (balanced -> green)
- 2021-12-31: late_risk_alert;unconfirmed_cash_raise (balanced -> green)
- 2022-01-31: late_risk_alert (balanced -> yellow)
- 2022-03-31: late_risk_alert;premature_growth_reentry;unconfirmed_cash_raise (growth_reentry_alert -> recovery)
- 2022-05-31: balanced_under_drawdown;unconfirmed_cash_raise (balanced -> yellow)
- 2022-06-30: balanced_under_drawdown (balanced -> red)
- 2022-07-29: balanced_under_drawdown (balanced -> yellow)
- 2022-08-31: late_risk_alert;balanced_under_drawdown (balanced -> yellow)
