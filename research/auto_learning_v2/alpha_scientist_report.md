# AutoLearning v2 Alpha Scientist Report

This run is research-only. It creates hypotheses and policy candidates, but production remains unchanged.

## Summary

- Novelty status: `novel_regime_watch`
- Known-regime confidence: 0.19
- Anomalies detected: 8
- Hypotheses generated: 7
- Challenger status: `blocked`
- Promotion status: `blocked`
- Next allowed stage: `shadow`

## Top Anomalies

- `bear_rs_theme_inversion`: Bear-regime trade journal IC favors RS acceleration while theme multipliers are negative.
- `concentrated_alpha_underallocated`: Concentrated has materially stronger standalone return/Sharpe but the orchestrator keeps it small.
- `main_broad_high_turnover`: Main remains broad while monthly turnover is high, which can dilute future_winner alpha.
- `sidecar_without_counterfactual_replay`: Several high-impact sidecars produce snapshots but still lack historical challenger replay.
- `bear_oversold_value_positive_ic`: Oversold value has positive IC in bear months, suggesting bear is not purely momentum-off.

## Hypotheses

- `bear_rs_reversal_v1`: In bear regimes, price-confirmed RS recovery and oversold value outperform static theme classification.
- `main_future_alpha_concentration_v1`: Main alpha is diluted by broad target N; an internal sleeve orchestrator can concentrate future_winner while capping early_scout.
- `concentrated_neutral_25_v1`: Concentrated should use a dynamic 20-30% risk budget when caps, entry quality, and weekly exits pass.
- `risk_governor_layered_exit_v1`: Risk sensing needs position-aware exits and better-replacement swaps rather than blunt portfolio cash cuts.
- `cluster_conviction_router_v1`: Trade clusters can route risk: strong clusters get conviction boost, weak clusters trigger caution/block rules.
- `alpha_sprint_breakout_fallback_v1`: Alpha Sprint should use breakout/RS/catalyst fallback signals until explosion_* features become nonzero and validated.
- `counterfactual_replay_priority_v1`: Policy creativity should be blocked from promotion until each sidecar has historical replay evidence.

## Production Safety

Production activation is blocked by design until full challenger replay, promotion gates, and human approval pass.
