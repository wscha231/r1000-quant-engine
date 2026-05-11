# AutoLearning Policy Candidate Summary

This candidate is proposal-only. It does not change production defaults.

## Evidence

- Main CAGR: 29.66%
- Main Sharpe: 1.7776333218625067
- Main MaxDD: -15.66%
- Main average stock names: 23.70
- Concentrated CAGR: 43.52%
- Concentrated Sharpe: 1.7435623649459715
- Concentrated MaxDD: -12.51%
- Main trade count: 765
- Concentrated trade count: 202
- Combined trade count: 967
- Combined win rate: 57.29%
- Feature-gate candidates carried forward: 2

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
