# AutoLearning Policy Candidate Summary

This candidate is proposal-only. It does not change production defaults.

## Evidence

- Main CAGR: 30.91%
- Main Sharpe: 1.6999187026810325
- Main MaxDD: -16.38%
- Main average stock names: 24.58
- Concentrated CAGR: 49.80%
- Concentrated Sharpe: 1.7607009713417816
- Concentrated MaxDD: -17.24%
- Main trade count: 775
- Concentrated trade count: 152
- Combined trade count: 927
- Combined win rate: 56.53%
- Feature-gate candidates carried forward: 8

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
