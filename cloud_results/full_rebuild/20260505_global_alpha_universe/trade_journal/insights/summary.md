# Trade Insights Summary

- trades analyzed: **536**
- generated: 2026-05-05 21:57 UTC

## 1. Signal IC by regime (rank correlation)
Top actionable findings:

**Worst signal x regime cells (potential gate candidates)**:
- `theme_phase_multiplier_primary` in **bear**: IC = -0.122
- `theme_phase_multiplier_primary` in **neutral**: IC = -0.115
- `theme_phase_multiplier_max` in **bear**: IC = -0.113

**Best signal x regime cells (amplify candidates)**:
- `rs_acceleration_score` in **bear**: IC = +0.141
- `rs_acceleration_score` in **bull**: IC = +0.139
- `theme_phase_multiplier_max` in **bull**: IC = +0.023

Full matrix in `ic_matrix.csv`.

## 2. Trade pattern clusters
**Worst pattern clusters (block candidates)**:
- cluster 2: win_rate=0.00, n=17, signature: theme_phase_multiplier_max=-5.01, theme_phase_multiplier_primary=-5.01, h6_dynamic_leader_score=-0.67
- cluster 6: win_rate=0.14, n=7, signature: theme_phase_multiplier_max=-2.40, theme_phase_multiplier_primary=-2.39, rs_acceleration_score=+0.96

**Best pattern clusters (amplify candidates)**:
- cluster 7: win_rate=0.67, n=90, signature: rs_acceleration_score=+1.10, h6_dynamic_leader_score=-0.62, theme_phase_multiplier_primary=+0.26
- cluster 3: win_rate=0.66, n=79, signature: h6_dynamic_leader_score=+1.64, rs_acceleration_score=+1.00, theme_phase_multiplier_max=+0.31

Full table in `cluster_winrate.csv`.

## 3. SHAP / model importance
_(no SHAP - no data)_

---

**Phase 18c next**: feed `ic_matrix.csv` + `cluster_winrate.csv` to `tools/feature_gate_proposal.py` to auto-draft `research/auto_feature_gates.yaml`.