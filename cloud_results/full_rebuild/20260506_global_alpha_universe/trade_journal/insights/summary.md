# Trade Insights Summary

- trades analyzed: **726**
- generated: 2026-05-06 19:35 UTC

## 1. Signal IC by regime (rank correlation)
Top actionable findings:

**Worst signal x regime cells (potential gate candidates)**:
- `theme_phase_multiplier_primary` in **bear**: IC = -0.095
- `theme_phase_multiplier_max` in **bear**: IC = -0.077
- `h6_dynamic_leader_score` in **bear**: IC = -0.038

**Best signal x regime cells (amplify candidates)**:
- `rs_acceleration_score` in **bull**: IC = +0.115
- `rs_acceleration_score` in **bear**: IC = +0.059
- `theme_phase_multiplier_max` in **bull**: IC = +0.057

Full matrix in `ic_matrix.csv`.

## 2. Trade pattern clusters
**Worst pattern clusters (block candidates)**:
- cluster 1: win_rate=0.00, n=13, signature: theme_phase_multiplier_max=-5.94, theme_phase_multiplier_primary=-5.91, h6_dynamic_leader_score=-0.62
- cluster 4: win_rate=0.50, n=20, signature: theme_phase_multiplier_max=-2.86, theme_phase_multiplier_primary=-2.83, rs_acceleration_score=+0.24

**Best pattern clusters (amplify candidates)**:
- cluster 6: win_rate=0.63, n=114, signature: rs_acceleration_score=+1.20, h6_dynamic_leader_score=-0.49, theme_phase_multiplier_primary=+0.23
- cluster 7: win_rate=0.61, n=84, signature: h6_dynamic_leader_score=+1.84, rs_acceleration_score=+1.04, theme_phase_multiplier_primary=+0.29

Full table in `cluster_winrate.csv`.

## 3. SHAP / model importance
_(no SHAP - no data)_

---

**Phase 18c next**: feed `ic_matrix.csv` + `cluster_winrate.csv` to `tools/feature_gate_proposal.py` to auto-draft `research/auto_feature_gates.yaml`.