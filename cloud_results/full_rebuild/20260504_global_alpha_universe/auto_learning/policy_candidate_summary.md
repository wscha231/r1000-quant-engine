# AutoLearning Policy Candidate Summary

This candidate is proposal-only. It does not change production defaults.

## Evidence

- Main CAGR: 21.40%
- Main Sharpe: 1.1831414285357171
- Main MaxDD: -27.27%
- Main average stock names: 25.51
- Concentrated CAGR: 34.85%
- Concentrated Sharpe: 1.4286886669635341
- Concentrated MaxDD: -22.94%
- Trade count: 695
- Feature-gate candidates carried forward: 4

## Candidate Scope

- Feature gates: carry forward existing bear regime proposals.
- Main v2: propose sleeve allocation and target-N policies.
- Concentrated: propose capacity, cap, entry, and exit policy candidates.
- Alpha Sprint: propose bull-only activation and risk rules.
- Orchestrator: propose regime capital maps for challenger backtest only.

## Validation

- Schema valid: True
- Issues: none

## Next Required Step

Build `tools/auto_policy_challenger.py` to run this policy as a challenger against legacy champion metrics.
