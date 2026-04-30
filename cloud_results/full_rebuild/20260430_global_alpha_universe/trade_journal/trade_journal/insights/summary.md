# Trade Insights Summary

- trades analyzed: **712**
- generated: 2026-04-30 23:02 UTC

## 1. Signal IC by regime (rank correlation)
Top actionable findings:

**Worst signal x regime cells (potential gate candidates)**:
- `theme_phase_multiplier_primary` in **bear**: IC = -0.107
- `theme_phase_multiplier_max` in **neutral**: IC = -0.103
- `theme_phase_multiplier_primary` in **neutral**: IC = -0.095

**Best signal x regime cells (amplify candidates)**:
- `rs_acceleration_score` in **bull**: IC = +0.122
- `rs_acceleration_score` in **bear**: IC = +0.046
- `rs_acceleration_score` in **neutral**: IC = +0.034

Full matrix in `ic_matrix.csv`.

## 2. Trade pattern clusters
**Worst pattern clusters (block candidates)**:
- cluster 2: win_rate=0.00, n=19, signature: theme_phase_multiplier_max=-5.13, theme_phase_multiplier_primary=-5.05, h6_dynamic_leader_score=-0.59
- cluster 4: win_rate=0.45, n=22, signature: theme_phase_multiplier_primary=-2.39, theme_phase_multiplier_max=-2.27, h6_dynamic_leader_score=-0.27

**Best pattern clusters (amplify candidates)**:
- cluster 0: win_rate=0.67, n=63, signature: rs_acceleration_score=-1.91, h6_dynamic_leader_score=-0.55, theme_phase_multiplier_primary=+0.11
- cluster 6: win_rate=0.64, n=74, signature: rs_acceleration_score=+1.44, h6_dynamic_leader_score=-0.45, theme_phase_multiplier_primary=+0.34

Full table in `cluster_winrate.csv`.

## 3. SHAP / model importance
_(no SHAP - no data)_

---

**Phase 18c next**: feed `ic_matrix.csv` + `cluster_winrate.csv` to `tools/feature_gate_proposal.py` to auto-draft `research/auto_feature_gates.yaml`.