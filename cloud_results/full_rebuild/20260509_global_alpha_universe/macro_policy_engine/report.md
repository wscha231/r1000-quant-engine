# Macro Policy Engine

Research-only sidecar. It does not change production weights.

- Status: `completed`
- Months: 83
- Latest risk state: `red`
- Latest style state: `cash_defense`
- Cash-raise confirmations: 2
- Confirmed cash raise: `True`
- Recommended cash floor: 28.0%
- Recommended target N: 16
- Monster exception capacity: 3.0%
- Monster exception allowed: `True`
- Cash-raise gate: `confirmed_long_trend_plus_liquidity_or_breadth`
- New-buy policy: `no_new_buy_except_confirmed_monster_scout_or_top_quality`
- Trim policy: `half_trim_then_exit_relative_losers`
- Action: `defend_half_trim_stale_leaders_no_tactical_new_buys`

## Risk State Counts

- crisis: 5
- green: 46
- recovery: 7
- red: 12
- yellow: 13

## Regime Speed Diagnostics

- balanced_under_drawdown: 12
- late_risk_alert: 10
- possible_cash_drag: 6
- premature_growth_reentry: 1
- unconfirmed_cash_raise: 14

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

- 2019-04-30: possible_cash_drag;unconfirmed_cash_raise (balanced -> green)
- 2021-03-31: possible_cash_drag;unconfirmed_cash_raise (growth_reentry_alert -> recovery)
- 2021-08-31: late_risk_alert;unconfirmed_cash_raise (balanced -> green)
- 2021-10-29: possible_cash_drag;unconfirmed_cash_raise (growth_reentry_alert -> recovery)
- 2021-12-31: late_risk_alert;unconfirmed_cash_raise (balanced -> green)
- 2022-01-31: late_risk_alert;balanced_under_drawdown (balanced -> yellow)
- 2022-02-28: balanced_under_drawdown (balanced -> yellow)
- 2022-03-31: late_risk_alert;premature_growth_reentry;unconfirmed_cash_raise (growth_reentry_alert -> green)
- 2022-05-31: balanced_under_drawdown (balanced -> red)
- 2022-06-30: balanced_under_drawdown (balanced -> red)
