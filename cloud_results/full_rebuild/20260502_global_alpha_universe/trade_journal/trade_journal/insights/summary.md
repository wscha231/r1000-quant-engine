# Trade Insights Summary

- trades analyzed: **499**
- generated: 2026-05-02 13:48 UTC

## 1. Signal IC by regime (rank correlation)
Top actionable findings:

**Worst signal x regime cells (potential gate candidates)**:
- `h6_dynamic_leader_score` in **bull**: IC = -0.084
- `theme_phase_multiplier_primary` in **bull**: IC = -0.082
- `theme_phase_multiplier_max` in **neutral**: IC = -0.076

**Best signal x regime cells (amplify candidates)**:
- `rs_acceleration_score` in **bear**: IC = +0.221
- `h6_dynamic_leader_score` in **neutral**: IC = +0.051
- `rs_acceleration_score` in **bull**: IC = +0.048

Full matrix in `ic_matrix.csv`.

## 2. Trade pattern clusters
**Worst pattern clusters (block candidates)**:
- cluster 1: win_rate=0.42, n=57, signature: theme_phase_multiplier_max=-1.84, theme_phase_multiplier_primary=-1.84, rs_acceleration_score=+0.59
- cluster 5: win_rate=0.51, n=41, signature: theme_phase_multiplier_max=-1.81, theme_phase_multiplier_primary=-1.81, rs_acceleration_score=-1.01

**Best pattern clusters (amplify candidates)**:
- cluster 2: win_rate=0.70, n=82, signature: rs_acceleration_score=-1.44, theme_phase_multiplier_primary=+0.51, theme_phase_multiplier_max=+0.50
- cluster 7: win_rate=0.63, n=65, signature: rs_acceleration_score=+1.04, theme_phase_multiplier_primary=+0.59, theme_phase_multiplier_max=+0.59

Full table in `cluster_winrate.csv`.

## 3. SHAP / model importance
_(no SHAP - no data)_

---

**Phase 18c next**: feed `ic_matrix.csv` + `cluster_winrate.csv` to `tools/feature_gate_proposal.py` to auto-draft `research/auto_feature_gates.yaml`.