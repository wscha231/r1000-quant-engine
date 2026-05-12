# Trade Insights Summary

- trades analyzed: **887**
- generated: 2026-05-12 23:08 UTC

## 1. Signal IC by regime (rank correlation)
Top actionable findings:

**Worst signal x regime cells (potential gate candidates)**:
- `selection_confirmation_score` in **deep_bear**: IC = -0.577
- `h6_dynamic_leader_score` in **deep_bear**: IC = -0.247
- `theme_phase_multiplier_primary` in **deep_bear**: IC = -0.231

**Best signal x regime cells (amplify candidates)**:
- `rs_acceleration_score` in **deep_bear**: IC = +0.190
- `theme_phase_multiplier_max` in **deep_bear**: IC = +0.161
- `selection_confirmation_score` in **neutral**: IC = +0.102

Full matrix in `ic_matrix.csv`.

## 2. Trade pattern clusters
**Worst pattern clusters (block candidates)**:
- cluster 7: win_rate=0.49, n=83, signature: selection_confirmation_score=-1.11, h6_dynamic_leader_score=-0.55, theme_phase_multiplier_max=+0.48
- cluster 3: win_rate=0.52, n=58, signature: theme_phase_multiplier_primary=-2.05, theme_phase_multiplier_max=-2.05, selection_confirmation_score=-1.74

**Best pattern clusters (amplify candidates)**:
- cluster 0: win_rate=0.63, n=130, signature: rs_acceleration_score=-1.60, h6_dynamic_leader_score=-0.48, theme_phase_multiplier_max=+0.46
- cluster 4: win_rate=0.63, n=99, signature: h6_dynamic_leader_score=+1.98, rs_acceleration_score=+0.93, selection_confirmation_score=+0.65

Full table in `cluster_winrate.csv`.

## 3. SHAP / model importance
_(no SHAP - no data)_

---

**Phase 18c next**: feed `ic_matrix.csv` + `cluster_winrate.csv` to `tools/feature_gate_proposal.py` to auto-draft `research/auto_feature_gates.yaml`.