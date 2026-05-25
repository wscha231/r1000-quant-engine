# Daily Crisis Monitor

- state: `GREEN`
- raw_state: `WATCH`
- auto_trade_allowed: `false`

## Reasons

- cash policy review active: target_cash_above_macro_floor_without_confirmation

## Guardrails

- VIX-only cash raise is forbidden.
- Single-name shakeout cash raise is forbidden.
- Liquidity/trend/credit confirmation is required for defense review.
- Reentry is review-only; this tool never buys automatically.
