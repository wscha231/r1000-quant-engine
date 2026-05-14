# AutoLearning Policy Candidate Summary

This candidate is proposal-only. It does not change production defaults.

## Evidence

- Main CAGR: 30.87%
- Main Sharpe: 1.7202960298994148
- Main MaxDD: -18.51%
- Main average stock names: 25.86
- Concentrated CAGR: 47.95%
- Concentrated Sharpe: 1.7573547279957327
- Concentrated MaxDD: -14.06%
- Main trade count: 771
- Concentrated trade count: 194
- Combined trade count: 965
- Combined win rate: 57.72%
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
