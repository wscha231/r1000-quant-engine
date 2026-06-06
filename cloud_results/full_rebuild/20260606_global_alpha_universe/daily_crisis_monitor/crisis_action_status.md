# Daily Crisis Monitor

- state: `GREEN`
- raw_state: `DEFENSE_REVIEW`
- auto_trade_allowed: `false`

## Reasons

- cash policy review active: below_combined_cash_target
- hard safety/risk issue count=2

## Guardrails

- VIX-only cash raise is forbidden.
- Single-name shakeout cash raise is forbidden.
- Liquidity/trend/credit confirmation is required for defense review.
- Reentry is review-only; this tool never buys automatically.
