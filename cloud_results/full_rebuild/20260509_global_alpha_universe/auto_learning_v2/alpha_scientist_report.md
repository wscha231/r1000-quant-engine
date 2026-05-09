# AutoLearning v2 Alpha Scientist Report

This run is research-only. It creates hypotheses and policy candidates, but production remains unchanged.

## Summary

- Novelty status: `novel_regime_watch`
- Known-regime confidence: 0.39
- Anomalies detected: 6
- Hypotheses generated: 6
- Challenger status: `blocked`
- Promotion status: `blocked`
- Next allowed stage: `shadow`

## Top Anomalies

- `concentrated_alpha_underallocated`: Concentrated has materially stronger standalone return/Sharpe but the orchestrator keeps it small.
- `main_broad_high_turnover`: Main remains broad while monthly turnover is high, which can dilute future_winner alpha.
- `sidecar_without_counterfactual_replay`: Several high-impact sidecars produce snapshots but still lack historical challenger replay.
- `risk_sensing_defense_return_tradeoff`: Simplified risk sensing improves drawdown but reduces CAGR/Sharpe in the aggressive matrix.
- `cluster_conviction_asymmetry`: Trade clusters show large dispersion between strong amplification candidates and weak/caution patterns.

## Hypotheses

- `main_future_alpha_concentration_v1`: Main alpha is diluted by broad target N; an internal sleeve orchestrator can concentrate future_winner while capping early_scout.
- `concentrated_neutral_25_v1`: Concentrated should use a dynamic 20-30% risk budget when caps, entry quality, and weekly exits pass.
- `risk_governor_layered_exit_v1`: Risk sensing needs position-aware exits and better-replacement swaps rather than blunt portfolio cash cuts.
- `cluster_conviction_router_v1`: Trade clusters can route risk: strong clusters get conviction boost, weak clusters trigger caution/block rules.
- `alpha_sprint_breakout_fallback_v1`: Alpha Sprint should use breakout/RS/catalyst fallback signals until explosion_* features become nonzero and validated.
- `counterfactual_replay_priority_v1`: Policy creativity should be blocked from promotion until each sidecar has historical replay evidence.

## Production Safety

Production activation is blocked by design until full challenger replay, promotion gates, and human approval pass.
