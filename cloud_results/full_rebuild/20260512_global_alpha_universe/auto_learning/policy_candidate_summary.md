# AutoLearning Policy Candidate Summary

This candidate is proposal-only. It does not change production defaults.

## Evidence

- Main CAGR: 28.91%
- Main Sharpe: 1.7438756765602594
- Main MaxDD: -13.56%
- Main average stock names: 22.13
- Concentrated CAGR: 46.68%
- Concentrated Sharpe: 1.7450442508169008
- Concentrated MaxDD: -18.57%
- Main trade count: 708
- Concentrated trade count: 204
- Combined trade count: 912
- Combined win rate: 58.88%
- Feature-gate candidates carried forward: 1

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
