# Trade Insights Summary

- trades analyzed: **532**
- generated: 2026-05-07 09:51 UTC

## 1. Signal IC by regime (rank correlation)
Top actionable findings:

**Worst signal x regime cells (potential gate candidates)**:
- `selection_confirmation_score` in **bear**: IC = -0.176
- `theme_phase_multiplier_max` in **neutral**: IC = -0.110
- `theme_phase_multiplier_primary` in **neutral**: IC = -0.100

**Best signal x regime cells (amplify candidates)**:
- `rs_acceleration_score` in **bull**: IC = +0.175
- `theme_phase_multiplier_max` in **bull**: IC = +0.100
- `h1_oversold_value_score` in **bear**: IC = +0.087

Full matrix in `ic_matrix.csv`.

## 2. Trade pattern clusters
**Worst pattern clusters (block candidates)**:
- cluster 3: win_rate=0.00, n=15, signature: theme_phase_multiplier_max=-5.19, theme_phase_multiplier_primary=-5.16, selection_confirmation_score=-3.25
- cluster 6: win_rate=0.40, n=10, signature: theme_phase_multiplier_max=-2.48, theme_phase_multiplier_primary=-2.45, entry_quality_score=+0.70

**Best pattern clusters (amplify candidates)**:
- cluster 2: win_rate=0.64, n=80, signature: rs_acceleration_score=+0.69, h6_dynamic_leader_score=-0.58, entry_quality_score=-0.52
- cluster 4: win_rate=0.61, n=56, signature: selection_confirmation_score=-2.32, h6_dynamic_leader_score=-0.70, entry_quality_score=-0.54

Full table in `cluster_winrate.csv`.

## 3. SHAP / model importance
_(no SHAP - no data)_

---

**Phase 18c next**: feed `ic_matrix.csv` + `cluster_winrate.csv` to `tools/feature_gate_proposal.py` to auto-draft `research/auto_feature_gates.yaml`.