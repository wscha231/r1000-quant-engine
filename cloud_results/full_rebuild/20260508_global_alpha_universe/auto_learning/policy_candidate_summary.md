# AutoLearning Policy Candidate Summary

This candidate is proposal-only. It does not change production defaults.

## Evidence

- Main CAGR: 28.12%
- Main Sharpe: 1.6202096991237043
- Main MaxDD: -15.92%
- Main average stock names: 24.98
- Concentrated CAGR: 47.71%
- Concentrated Sharpe: 1.749531723854578
- Concentrated MaxDD: -19.72%
- Main trade count: 740
- Concentrated trade count: 150
- Combined trade count: 890
- Combined win rate: 59.21%
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
