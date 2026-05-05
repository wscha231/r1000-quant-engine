# Trade Insights Summary

- trades analyzed: **690**
- generated: 2026-05-05 17:20 UTC

## 1. Signal IC by regime (rank correlation)
Top actionable findings:

**Worst signal x regime cells (potential gate candidates)**:
- `theme_phase_multiplier_primary` in **bear**: IC = -0.112
- `theme_phase_multiplier_max` in **bear**: IC = -0.093
- `theme_phase_multiplier_max` in **neutral**: IC = -0.086

**Best signal x regime cells (amplify candidates)**:
- `rs_acceleration_score` in **bear**: IC = +0.168
- `rs_acceleration_score` in **bull**: IC = +0.131
- `h1_oversold_value_score` in **bear**: IC = +0.089

Full matrix in `ic_matrix.csv`.

## 2. Trade pattern clusters
**Worst pattern clusters (block candidates)**:
- cluster 4: win_rate=0.00, n=11, signature: theme_phase_multiplier_max=-6.15, theme_phase_multiplier_primary=-6.12, h6_dynamic_leader_score=-0.64
- cluster 6: win_rate=0.50, n=251, signature: h6_dynamic_leader_score=-0.54, theme_phase_multiplier_primary=+0.24, theme_phase_multiplier_max=+0.23

**Best pattern clusters (amplify candidates)**:
- cluster 0: win_rate=0.66, n=99, signature: h6_dynamic_leader_score=+1.72, rs_acceleration_score=+0.96, theme_phase_multiplier_max=+0.25
- cluster 5: win_rate=0.63, n=100, signature: rs_acceleration_score=+1.25, h6_dynamic_leader_score=-0.51, theme_phase_multiplier_max=+0.24

Full table in `cluster_winrate.csv`.

## 3. SHAP / model importance
_(no SHAP - no data)_

---

**Phase 18c next**: feed `ic_matrix.csv` + `cluster_winrate.csv` to `tools/feature_gate_proposal.py` to auto-draft `research/auto_feature_gates.yaml`.