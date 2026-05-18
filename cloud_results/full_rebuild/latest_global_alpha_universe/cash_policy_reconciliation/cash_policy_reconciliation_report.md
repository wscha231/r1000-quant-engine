# Cash Policy Reconciliation

Latest-snapshot diagnostic only. No portfolio weights are changed.

## Verdict

- status: `completed`
- review required: `True`
- decision point: target_cash_exceeds_macro_floor_without_confirmation

## Key Values

- macro risk/style: `green` / `breakout_growth`
- macro cash floor: 3.00%
- orchestrator target cash: 25.00%
- current account cash: 0.93%
- target cash above macro floor: 22.00%
- capacity leftover cash: 25.00%
- conflict merge cash: 0.00%
- opportunity cost at 10% return assumption: 2.20%

## Notes

- A high orchestrator target cash in a green/recovery macro state should be treated as a decision point, not as confirmed risk defense.
- Capacity leftover cash means mandate weights sum below 100%; conflict merge cash means max-merge overlap reduced invested exposure.
- This sidecar does not redeploy cash. It only separates macro defense from mechanical cash drag candidates.
