# AutoLearning Policy Candidate Summary

This candidate is proposal-only. It does not change production defaults.

## Evidence

- Main CAGR: 27.32%
- Main Sharpe: 1.6397079003602735
- Main MaxDD: -17.87%
- Main average stock names: 23.87
- Concentrated CAGR: 39.86%
- Concentrated Sharpe: 1.7049580372452717
- Concentrated MaxDD: -16.58%
- Main trade count: 911
- Concentrated trade count: 305
- Combined trade count: 1216
- Combined win rate: 59.21%
- Feature-gate candidates carried forward: 3

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
