# AutoLearning v2 Alpha Scientist Report

This run is research-only. It creates hypotheses and policy candidates, but production remains unchanged.

## Summary

- Novelty status: `regime_assumption_review`
- Known-regime confidence: 0.59
- Anomalies detected: 4
- Hypotheses generated: 4
- Challenger status: `blocked`
- Promotion status: `blocked`
- Next allowed stage: `shadow`

## Top Anomalies

- `concentrated_alpha_underallocated`: Concentrated has materially stronger standalone return/Sharpe but the orchestrator keeps it small.
- `sidecar_without_counterfactual_replay`: Several high-impact sidecars produce snapshots but still lack historical challenger replay.
- `risk_sensing_defense_return_tradeoff`: Simplified risk sensing improves drawdown but reduces CAGR/Sharpe in the aggressive matrix.
- `explosion_stack_dormant`: Explosion entry/exit rows exist in the trade journal IC matrix but have no numeric IC evidence.

## Hypotheses

- `concentrated_neutral_25_v1`: Concentrated should use a dynamic 20-30% risk budget when caps, entry quality, and weekly exits pass.
- `risk_governor_layered_exit_v1`: Risk sensing needs position-aware exits and better-replacement swaps rather than blunt portfolio cash cuts.
- `alpha_sprint_breakout_fallback_v1`: Alpha Sprint should use breakout/RS/catalyst fallback signals until explosion_* features become nonzero and validated.
- `counterfactual_replay_priority_v1`: Policy creativity should be blocked from promotion until each sidecar has historical replay evidence.

## Production Safety

Production activation is blocked by design until full challenger replay, promotion gates, and human approval pass.
