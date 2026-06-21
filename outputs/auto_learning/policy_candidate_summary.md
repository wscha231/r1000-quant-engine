# AutoLearning Policy Candidate Summary

This candidate is proposal-only. It does not change production defaults.

## Evidence

- Main CAGR: 33.07%
- Main Sharpe: 1.844916769060813
- Main MaxDD: -15.84%
- Main average stock names: 25.30
- Concentrated CAGR: 50.95%
- Concentrated Sharpe: 1.590500881786434
- Concentrated MaxDD: -18.52%
- Main trade count: 742
- Concentrated trade count: 163
- Combined trade count: 905
- Combined win rate: 55.03%
- Feature-gate candidates carried forward: 5

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
