# AutoLearning Policy Candidate Summary

This candidate is proposal-only. It does not change production defaults.

## Evidence

- Main CAGR: 33.19%
- Main Sharpe: 1.843716696195194
- Main MaxDD: -14.46%
- Main average stock names: 26.00
- Concentrated CAGR: 50.60%
- Concentrated Sharpe: 1.7433265841651264
- Concentrated MaxDD: -16.49%
- Main trade count: 769
- Concentrated trade count: 203
- Combined trade count: 972
- Combined win rate: 54.94%
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
