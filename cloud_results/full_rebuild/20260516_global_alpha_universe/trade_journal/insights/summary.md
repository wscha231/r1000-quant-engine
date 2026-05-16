# Trade Insights Summary

- trades analyzed: **1095**
- generated: 2026-05-16 18:05 UTC

## 1. Signal IC by regime (rank correlation)
Top actionable findings:

**Worst signal x regime cells (potential gate candidates)**:
- `theme_phase_multiplier_primary` in **strong_bull**: IC = -0.572
- `theme_phase_multiplier_max` in **strong_bull**: IC = -0.572
- `theme_phase_multiplier_primary` in **bear**: IC = -0.175

**Best signal x regime cells (amplify candidates)**:
- `entry_quality_score` in **strong_bull**: IC = +0.238
- `rs_acceleration_score` in **strong_bull**: IC = +0.218
- `entry_quality_score` in **bull**: IC = +0.136

Full matrix in `ic_matrix.csv`.

## 2. Trade pattern clusters
**Worst pattern clusters (block candidates)**:
- cluster 6: win_rate=0.51, n=156, signature: theme_phase_multiplier_primary=+0.72, theme_phase_multiplier_max=+0.72, portfolio_monster_early_score=-0.67
- cluster 5: win_rate=0.53, n=99, signature: rs_acceleration_score=-1.97, theme_phase_multiplier_primary=+0.72, theme_phase_multiplier_max=+0.72

**Best pattern clusters (amplify candidates)**:
- cluster 7: win_rate=0.61, n=153, signature: entry_quality_score=+1.43, rs_acceleration_score=+0.74, theme_phase_multiplier_max=+0.68
- cluster 1: win_rate=0.58, n=165, signature: h6_dynamic_leader_score=+2.21, selection_confirmation_score=+0.87, theme_phase_multiplier_primary=+0.74

Full table in `cluster_winrate.csv`.

## 3. SHAP / model importance
_(no SHAP - no data)_

---

**Phase 18c next**: feed `ic_matrix.csv` + `cluster_winrate.csv` to `tools/feature_gate_proposal.py` to auto-draft `research/auto_feature_gates.yaml`.