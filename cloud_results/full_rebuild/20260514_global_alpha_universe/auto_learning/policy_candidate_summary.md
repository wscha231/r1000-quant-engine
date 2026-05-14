# AutoLearning Policy Candidate Summary

This candidate is proposal-only. It does not change production defaults.

## Evidence

- Main CAGR: 29.79%
- Main Sharpe: 1.7111635028673302
- Main MaxDD: -16.65%
- Main average stock names: 25.35
- Concentrated CAGR: 48.62%
- Concentrated Sharpe: 1.733861454092223
- Concentrated MaxDD: -21.05%
- Main trade count: 759
- Concentrated trade count: 159
- Combined trade count: 918
- Combined win rate: 56.10%
- Feature-gate candidates carried forward: 0

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
