# Trade Insights Summary

- trades analyzed: **523**
- generated: 2026-05-04 03:05 UTC

## 1. Signal IC by regime (rank correlation)
Top actionable findings:

**Worst signal x regime cells (potential gate candidates)**:
- `h6_dynamic_leader_score` in **bear**: IC = -0.119
- `rs_acceleration_score` in **bull**: IC = -0.112
- `theme_phase_multiplier_primary` in **bull**: IC = -0.041

**Best signal x regime cells (amplify candidates)**:
- `rs_acceleration_score` in **bear**: IC = +0.111
- `theme_phase_multiplier_primary` in **neutral**: IC = +0.076
- `h6_dynamic_leader_score` in **bull**: IC = +0.076

Full matrix in `ic_matrix.csv`.

## 2. Trade pattern clusters
**Worst pattern clusters (block candidates)**:
- cluster 2: win_rate=0.00, n=11, signature: theme_phase_multiplier_max=-5.52, theme_phase_multiplier_primary=-5.33, h6_dynamic_leader_score=-0.58
- cluster 4: win_rate=0.33, n=18, signature: theme_phase_multiplier_primary=-2.54, theme_phase_multiplier_max=-2.27, h6_dynamic_leader_score=-0.40

**Best pattern clusters (amplify candidates)**:
- cluster 0: win_rate=0.66, n=59, signature: h6_dynamic_leader_score=+1.91, rs_acceleration_score=+1.07, theme_phase_multiplier_max=+0.27
- cluster 7: win_rate=0.59, n=51, signature: h6_dynamic_leader_score=+1.74, rs_acceleration_score=-0.45, theme_phase_multiplier_max=+0.19

Full table in `cluster_winrate.csv`.

## 3. SHAP / model importance
_(no SHAP - no data)_

---

**Phase 18c next**: feed `ic_matrix.csv` + `cluster_winrate.csv` to `tools/feature_gate_proposal.py` to auto-draft `research/auto_feature_gates.yaml`.