# AutoLearning Policy Candidate Summary

This candidate is proposal-only. It does not change production defaults.

## Evidence

- Main CAGR: 30.62%
- Main Sharpe: 1.687330574762984
- Main MaxDD: -16.88%
- Main average stock names: 26.20
- Concentrated CAGR: 56.30%
- Concentrated Sharpe: 1.8844929489164732
- Concentrated MaxDD: -14.83%
- Main trade count: 813
- Concentrated trade count: 231
- Combined trade count: 1044
- Combined win rate: 56.80%
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
