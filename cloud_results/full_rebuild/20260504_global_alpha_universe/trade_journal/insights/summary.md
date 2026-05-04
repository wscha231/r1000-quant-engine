# Trade Insights Summary

- trades analyzed: **624**
- generated: 2026-05-04 04:50 UTC

## 1. Signal IC by regime (rank correlation)
Top actionable findings:

**Worst signal x regime cells (potential gate candidates)**:
- `theme_phase_multiplier_primary` in **neutral**: IC = -0.133
- `theme_phase_multiplier_max` in **neutral**: IC = -0.120
- `h6_dynamic_leader_score` in **neutral**: IC = -0.046

**Best signal x regime cells (amplify candidates)**:
- `rs_acceleration_score` in **bear**: IC = +0.062
- `theme_phase_multiplier_max` in **bull**: IC = +0.034
- `rs_acceleration_score` in **bull**: IC = +0.031

Full matrix in `ic_matrix.csv`.

## 2. Trade pattern clusters
**Worst pattern clusters (block candidates)**:
- cluster 4: win_rate=0.00, n=10, signature: theme_phase_multiplier_max=-5.76, theme_phase_multiplier_primary=-5.65, h6_dynamic_leader_score=-0.59
- cluster 1: win_rate=0.52, n=227, signature: h6_dynamic_leader_score=-0.50, theme_phase_multiplier_primary=+0.24, theme_phase_multiplier_max=+0.23

**Best pattern clusters (amplify candidates)**:
- cluster 6: win_rate=0.63, n=101, signature: rs_acceleration_score=+1.20, h6_dynamic_leader_score=-0.52, theme_phase_multiplier_primary=+0.34
- cluster 5: win_rate=0.63, n=120, signature: rs_acceleration_score=-1.42, h6_dynamic_leader_score=-0.55, theme_phase_multiplier_primary=+0.09

Full table in `cluster_winrate.csv`.

## 3. SHAP / model importance
_(no SHAP - no data)_

---

**Phase 18c next**: feed `ic_matrix.csv` + `cluster_winrate.csv` to `tools/feature_gate_proposal.py` to auto-draft `research/auto_feature_gates.yaml`.