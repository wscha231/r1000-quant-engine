# Trade Insights Summary

- trades analyzed: **687**
- generated: 2026-04-30 18:22 UTC

## 1. Signal IC by regime (rank correlation)
Top actionable findings:

**Worst signal x regime cells (potential gate candidates)**:
- `h6_dynamic_leader_score` in **bear**: IC = -0.136
- `theme_phase_multiplier_max` in **neutral**: IC = -0.121
- `theme_phase_multiplier_primary` in **neutral**: IC = -0.094

**Best signal x regime cells (amplify candidates)**:
- `theme_phase_multiplier_primary` in **bull**: IC = +0.055
- `theme_phase_multiplier_max` in **bull**: IC = +0.039
- `rs_acceleration_score` in **bear**: IC = +0.024

Full matrix in `ic_matrix.csv`.

## 2. Trade pattern clusters
**Worst pattern clusters (block candidates)**:
- cluster 2: win_rate=0.00, n=22, signature: theme_phase_multiplier_max=-4.79, theme_phase_multiplier_primary=-4.76, h6_dynamic_leader_score=-0.59
- cluster 5: win_rate=0.38, n=21, signature: theme_phase_multiplier_primary=-2.24, theme_phase_multiplier_max=-2.16, h6_dynamic_leader_score=-0.26

**Best pattern clusters (amplify candidates)**:
- cluster 7: win_rate=0.68, n=75, signature: rs_acceleration_score=-1.76, h6_dynamic_leader_score=-0.54, theme_phase_multiplier_primary=+0.14
- cluster 0: win_rate=0.64, n=56, signature: rs_acceleration_score=+1.62, h6_dynamic_leader_score=-0.49, theme_phase_multiplier_max=+0.25

Full table in `cluster_winrate.csv`.

## 3. SHAP / model importance
_(no SHAP - no data)_

---

**Phase 18c next**: feed `ic_matrix.csv` + `cluster_winrate.csv` to `tools/feature_gate_proposal.py` to auto-draft `research/auto_feature_gates.yaml`.