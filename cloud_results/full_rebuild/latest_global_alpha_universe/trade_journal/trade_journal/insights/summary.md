# Trade Insights Summary

- trades analyzed: **696**
- generated: 2026-05-02 10:40 UTC

## 1. Signal IC by regime (rank correlation)
Top actionable findings:

**Worst signal x regime cells (potential gate candidates)**:
- `theme_phase_multiplier_primary` in **neutral**: IC = -0.103
- `theme_phase_multiplier_max` in **neutral**: IC = -0.075
- `theme_phase_multiplier_primary` in **bear**: IC = -0.038

**Best signal x regime cells (amplify candidates)**:
- `rs_acceleration_score` in **bear**: IC = +0.102
- `theme_phase_multiplier_max` in **bull**: IC = +0.052
- `h6_dynamic_leader_score` in **bull**: IC = +0.041

Full matrix in `ic_matrix.csv`.

## 2. Trade pattern clusters
**Worst pattern clusters (block candidates)**:
- cluster 4: win_rate=0.00, n=16, signature: theme_phase_multiplier_max=-5.39, theme_phase_multiplier_primary=-5.30, h6_dynamic_leader_score=-0.60
- cluster 1: win_rate=0.39, n=23, signature: theme_phase_multiplier_primary=-2.51, theme_phase_multiplier_max=-2.35, h6_dynamic_leader_score=-0.18

**Best pattern clusters (amplify candidates)**:
- cluster 5: win_rate=0.64, n=78, signature: h6_dynamic_leader_score=+1.90, rs_acceleration_score=+1.07, theme_phase_multiplier_max=+0.29
- cluster 6: win_rate=0.60, n=124, signature: rs_acceleration_score=-1.49, h6_dynamic_leader_score=-0.54, theme_phase_multiplier_primary=+0.11

Full table in `cluster_winrate.csv`.

## 3. SHAP / model importance
_(no SHAP - no data)_

---

**Phase 18c next**: feed `ic_matrix.csv` + `cluster_winrate.csv` to `tools/feature_gate_proposal.py` to auto-draft `research/auto_feature_gates.yaml`.