# Daily Crisis Monitor

- state: `GREEN`
- raw_state: `WATCH`
- auto_trade_allowed: `false`

## Reasons

- long-crisis learned state=GREEN score=0.067 date=2026-07-02 cash_gate=below_cash_raise_zone
- cash policy review active: cash_close_to_target

## Paper Action Candidates

- paper_actions_only: `true`
- production_mutation_allowed: `false`

| Action | Priority | Scope/Ticker | Detail |
| --- | ---: | --- | --- |
| no_op | 0 |  |  |

## Long Crisis Learning

- latest_date: `2026-07-02`
- crisis_score: `0.0665878422606865`
- cash_gate_reason: `below_cash_raise_zone`
- future drawdown labels are excluded from daily monitor decisions.

## Guardrails

- VIX-only cash raise is forbidden.
- Single-name shakeout cash raise is forbidden.
- Liquidity/trend/credit confirmation is required for defense review.
- Reentry is review-only; this tool never buys automatically.
