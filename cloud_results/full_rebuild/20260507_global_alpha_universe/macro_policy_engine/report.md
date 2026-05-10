# Macro Policy Engine

Research-only sidecar. It does not change production weights.

- Status: `completed`
- Months: 83
- Latest risk state: `red`
- Latest style state: `cash_defense`
- Recommended cash floor: 28.0%
- Recommended target N: 16
- New-buy policy: `no_new_buy_except_top_quality_or_recovery`
- Trim policy: `half_trim_then_exit_relative_losers`
- Action: `defend_half_trim_stale_leaders_no_tactical_new_buys`

## Risk State Counts

- crisis: 5
- green: 50
- recovery: 7
- red: 11
- yellow: 10

## Regime Speed Diagnostics

- balanced_under_drawdown: 7
- late_risk_alert: 11
- possible_cash_drag: 5
- premature_growth_reentry: 1

## Interpretation

Use `macro_policy_by_month.csv` to A/B a slower re-entry / faster
defense policy in Main v2. Use `regime_speed_audit.csv` to find
months where the current regime label returned to balanced too early
or kept excessive cash after risk had already normalized.

Production promotion requires a separate historical challenger replay.

## First Diagnostics

- 2021-08-31: late_risk_alert (balanced -> green)
- 2021-10-29: possible_cash_drag (growth_reentry_alert -> recovery)
- 2021-11-30: possible_cash_drag (balanced -> green)
- 2021-12-31: late_risk_alert (balanced -> green)
- 2022-01-31: late_risk_alert (balanced -> green)
- 2022-03-31: late_risk_alert;premature_growth_reentry (growth_reentry_alert -> yellow)
- 2022-05-31: balanced_under_drawdown (balanced -> red)
- 2022-06-30: balanced_under_drawdown (balanced -> yellow)
- 2022-07-29: late_risk_alert;balanced_under_drawdown (balanced -> yellow)
- 2022-08-31: balanced_under_drawdown (balanced -> crisis)
