# AutoLearning Policy Candidate Summary

This candidate is proposal-only. It does not change production defaults.

## Evidence

- Main CAGR: 20.29%
- Main Sharpe: 1.4848607897809738
- Main MaxDD: -15.28%
- Main average stock names: 23.91
- Concentrated CAGR: 28.11%
- Concentrated Sharpe: 1.583793078975827
- Concentrated MaxDD: -11.45%
- Main trade count: 737
- Concentrated trade count: 358
- Combined trade count: 1095
- Combined win rate: 55.98%
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
