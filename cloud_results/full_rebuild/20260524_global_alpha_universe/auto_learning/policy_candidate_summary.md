# AutoLearning Policy Candidate Summary

This candidate is proposal-only. It does not change production defaults.

## Evidence

- Main CAGR: 28.45%
- Main Sharpe: 1.7143210142406808
- Main MaxDD: -18.05%
- Main average stock names: 20.10
- Concentrated CAGR: 47.60%
- Concentrated Sharpe: 1.7801446965137586
- Concentrated MaxDD: -23.02%
- Main trade count: 591
- Concentrated trade count: 164
- Combined trade count: 755
- Combined win rate: 56.29%
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
