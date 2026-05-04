# Trade Insights Summary

- trades analyzed: **695**
- generated: 2026-05-04 18:42 UTC

## 1. Signal IC by regime (rank correlation)
Top actionable findings:

**Worst signal x regime cells (potential gate candidates)**:
- `theme_phase_multiplier_max` in **neutral**: IC = -0.052
- `theme_phase_multiplier_primary` in **neutral**: IC = -0.043
- `theme_phase_multiplier_primary` in **bear**: IC = -0.034

**Best signal x regime cells (amplify candidates)**:
- `rs_acceleration_score` in **bear**: IC = +0.152
- `h6_dynamic_leader_score` in **bull**: IC = +0.083
- `theme_phase_multiplier_max` in **bull**: IC = +0.075

Full matrix in `ic_matrix.csv`.

## 2. Trade pattern clusters
**Worst pattern clusters (block candidates)**:
- cluster 2: win_rate=0.00, n=11, signature: theme_phase_multiplier_max=-6.22, theme_phase_multiplier_primary=-6.06, h6_dynamic_leader_score=-0.60
- cluster 7: win_rate=0.54, n=251, signature: h6_dynamic_leader_score=-0.49, theme_phase_multiplier_primary=+0.24, theme_phase_multiplier_max=+0.22

**Best pattern clusters (amplify candidates)**:
- cluster 0: win_rate=0.68, n=97, signature: h6_dynamic_leader_score=+1.92, rs_acceleration_score=+0.87, theme_phase_multiplier_max=+0.26
- cluster 3: win_rate=0.60, n=139, signature: rs_acceleration_score=-1.37, h6_dynamic_leader_score=-0.56, theme_phase_multiplier_max=+0.09

Full table in `cluster_winrate.csv`.

## 3. SHAP / model importance
_(no SHAP - no data)_

---

**Phase 18c next**: feed `ic_matrix.csv` + `cluster_winrate.csv` to `tools/feature_gate_proposal.py` to auto-draft `research/auto_feature_gates.yaml`.