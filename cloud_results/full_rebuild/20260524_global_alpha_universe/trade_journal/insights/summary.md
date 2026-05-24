# Trade Insights Summary

- trades analyzed: **755**
- generated: 2026-05-24 18:39 UTC

## 1. Signal IC by regime (rank correlation)
Top actionable findings:

**Worst signal x regime cells (potential gate candidates)**:
- `theme_phase_multiplier_primary` in **bear**: IC = -0.140
- `theme_phase_multiplier_primary` in **bull**: IC = -0.118
- `theme_phase_multiplier_max` in **bear**: IC = -0.090

**Best signal x regime cells (amplify candidates)**:
- `entry_quality_score` in **bull**: IC = +0.224
- `selection_confirmation_score` in **bull**: IC = +0.152
- `selection_confirmation_score` in **neutral**: IC = +0.126

Full matrix in `ic_matrix.csv`.

## 2. Trade pattern clusters
**Worst pattern clusters (block candidates)**:
- cluster 2: win_rate=0.47, n=124, signature: rs_acceleration_score=+0.86, theme_phase_multiplier_primary=+0.57, theme_phase_multiplier_max=+0.57
- cluster 0: win_rate=0.52, n=122, signature: rs_acceleration_score=-1.54, theme_phase_multiplier_primary=+0.55, theme_phase_multiplier_max=+0.55

**Best pattern clusters (amplify candidates)**:
- cluster 6: win_rate=0.62, n=176, signature: entry_quality_score=+1.39, selection_confirmation_score=+0.57, portfolio_monster_early_score=-0.52
- cluster 4: win_rate=0.61, n=80, signature: h6_dynamic_leader_score=+1.93, rs_acceleration_score=+0.96, selection_confirmation_score=+0.73

Full table in `cluster_winrate.csv`.

## 3. SHAP / model importance
_(no SHAP - no data)_

---

**Phase 18c next**: feed `ic_matrix.csv` + `cluster_winrate.csv` to `tools/feature_gate_proposal.py` to auto-draft `research/auto_feature_gates.yaml`.