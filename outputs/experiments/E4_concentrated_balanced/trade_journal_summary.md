# Trade Insights Summary

- trades analyzed: **695**
- generated: 2026-05-02 07:26 UTC

## 1. Signal IC by regime (rank correlation)
Top actionable findings:

**Worst signal x regime cells (potential gate candidates)**:
- `theme_phase_multiplier_primary` in **bear**: IC = -0.119
- `theme_phase_multiplier_max` in **bear**: IC = -0.087
- `h6_dynamic_leader_score` in **bear**: IC = -0.026

**Best signal x regime cells (amplify candidates)**:
- `rs_acceleration_score` in **bear**: IC = +0.141
- `h1_oversold_value_score` in **bear**: IC = +0.119
- `rs_acceleration_score` in **neutral**: IC = +0.054

Full matrix in `ic_matrix.csv`.

## 2. Trade pattern clusters
**Worst pattern clusters (block candidates)**:
- cluster 6: win_rate=0.00, n=19, signature: theme_phase_multiplier_max=-5.04, theme_phase_multiplier_primary=-4.92, h6_dynamic_leader_score=-0.59
- cluster 0: win_rate=0.48, n=56, signature: h6_dynamic_leader_score=+1.62, rs_acceleration_score=-0.57, theme_phase_multiplier_primary=+0.23

**Best pattern clusters (amplify candidates)**:
- cluster 5: win_rate=0.67, n=94, signature: h6_dynamic_leader_score=+1.89, rs_acceleration_score=+0.89, theme_phase_multiplier_max=+0.28
- cluster 1: win_rate=0.63, n=125, signature: rs_acceleration_score=+1.14, h6_dynamic_leader_score=-0.47, theme_phase_multiplier_primary=+0.29

Full table in `cluster_winrate.csv`.

## 3. SHAP / model importance
_(no SHAP - no data)_

---

**Phase 18c next**: feed `ic_matrix.csv` + `cluster_winrate.csv` to `tools/feature_gate_proposal.py` to auto-draft `research/auto_feature_gates.yaml`.