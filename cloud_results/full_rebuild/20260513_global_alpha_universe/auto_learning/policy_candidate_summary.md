# AutoLearning Policy Candidate Summary

This candidate is proposal-only. It does not change production defaults.

## Evidence

- Main CAGR: 28.31%
- Main Sharpe: 1.682607622313662
- Main MaxDD: -16.24%
- Main average stock names: 19.27
- Concentrated CAGR: 48.19%
- Concentrated Sharpe: 1.8368841417296249
- Concentrated MaxDD: -16.36%
- Main trade count: 573
- Concentrated trade count: 199
- Combined trade count: 772
- Combined win rate: 58.16%
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
