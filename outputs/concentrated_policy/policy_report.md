# Concentrated Policy Audit

This is a research-only policy audit. It does not change concentrated selection, weighting, or execution.

## Latest Sleeve

- Regime: `neutral`
- Current positions: 5
- Current concentrated weight sum: 100.00%
- Balanced recommended capacity: 20.00%
- Balanced recommended target N: 5
- Cap violations: 2
- Entry-gate blocked current holdings: 5
- Risk-gate blocked current holdings: 3

## Historical Reference

- CAGR: 34.85%
- Sharpe: 1.4286886669635341
- MaxDD: -22.94%

## Current Holdings Audit

- PR: weight 26.24%, conviction 1.015, entry blocked(entry_quality_ok), risk pass
- MRVL: weight 20.28%, conviction 1.906, entry blocked(entry_quality_ok), risk pass
- AMKR: weight 20.18%, conviction 0.788, entry blocked(entry_quality_ok), risk blocked(rs_not_decaying)
- CIEN: weight 18.65%, conviction 1.809, entry blocked(entry_quality_ok), risk blocked(rs_not_decaying)
- GLW: weight 14.65%, conviction 1.904, entry blocked(entry_quality_ok), risk blocked(rs_not_decaying)

## Policy Maps

- Conservative, balanced, and aggressive capacity maps are exported in `policy_maps_latest.json`.
- Promotion path remains: cap audit -> timing backtest -> orchestrator backtest -> approval.
