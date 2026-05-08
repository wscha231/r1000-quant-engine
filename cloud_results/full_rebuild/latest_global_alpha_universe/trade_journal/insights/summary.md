# Trade Insights Summary

- trades analyzed: **890**
- generated: 2026-05-08 12:17 UTC

## 1. Signal IC by regime (rank correlation)
Top actionable findings:

**Worst signal x regime cells (potential gate candidates)**:
- `entry_quality_score` in **bear**: IC = -0.112
- `theme_phase_multiplier_max` in **neutral**: IC = -0.081
- `theme_phase_multiplier_primary` in **neutral**: IC = -0.069

**Best signal x regime cells (amplify candidates)**:
- `rs_acceleration_score` in **bull**: IC = +0.130
- `entry_quality_score` in **bull**: IC = +0.067
- `selection_confirmation_score` in **neutral**: IC = +0.064

Full matrix in `ic_matrix.csv`.

## 2. Trade pattern clusters
**Worst pattern clusters (block candidates)**:
- cluster 5: win_rate=0.49, n=74, signature: selection_confirmation_score=-1.13, h6_dynamic_leader_score=-0.56, theme_phase_multiplier_primary=+0.48
- cluster 7: win_rate=0.52, n=56, signature: theme_phase_multiplier_max=-2.05, theme_phase_multiplier_primary=-2.05, selection_confirmation_score=-1.75

**Best pattern clusters (amplify candidates)**:
- cluster 0: win_rate=0.64, n=108, signature: portfolio_risk_entry_block_score=+2.52, portfolio_monster_early_score=+2.22, theme_phase_multiplier_max=-2.05
- cluster 2: win_rate=0.63, n=142, signature: rs_acceleration_score=-1.56, theme_phase_multiplier_max=+0.46, theme_phase_multiplier_primary=+0.46

Full table in `cluster_winrate.csv`.

## 3. SHAP / model importance
_(no SHAP - no data)_

---

**Phase 18c next**: feed `ic_matrix.csv` + `cluster_winrate.csv` to `tools/feature_gate_proposal.py` to auto-draft `research/auto_feature_gates.yaml`.