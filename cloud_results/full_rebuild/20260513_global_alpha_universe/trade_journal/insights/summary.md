# Trade Insights Summary

- trades analyzed: **772**
- generated: 2026-05-13 14:25 UTC

## 1. Signal IC by regime (rank correlation)
Top actionable findings:

**Worst signal x regime cells (potential gate candidates)**:
- `theme_phase_multiplier_max` in **neutral**: IC = -0.089
- `theme_phase_multiplier_primary` in **neutral**: IC = -0.068
- `h6_dynamic_leader_score` in **bear**: IC = -0.044

**Best signal x regime cells (amplify candidates)**:
- `theme_phase_multiplier_max` in **bull**: IC = +0.134
- `selection_confirmation_score` in **neutral**: IC = +0.114
- `rs_acceleration_score` in **bear**: IC = +0.087

Full matrix in `ic_matrix.csv`.

## 2. Trade pattern clusters
**Worst pattern clusters (block candidates)**:
- cluster 0: win_rate=0.53, n=120, signature: rs_acceleration_score=+0.71, theme_phase_multiplier_max=+0.61, theme_phase_multiplier_primary=+0.60
- cluster 1: win_rate=0.55, n=71, signature: theme_phase_multiplier_max=-1.60, theme_phase_multiplier_primary=-1.60, selection_confirmation_score=-1.45

**Best pattern clusters (amplify candidates)**:
- cluster 3: win_rate=0.64, n=92, signature: h6_dynamic_leader_score=+1.97, rs_acceleration_score=+1.02, selection_confirmation_score=+0.75
- cluster 5: win_rate=0.63, n=141, signature: portfolio_risk_entry_block_score=+1.96, portfolio_monster_early_score=+1.70, theme_phase_multiplier_max=-1.60

Full table in `cluster_winrate.csv`.

## 3. SHAP / model importance
_(no SHAP - no data)_

---

**Phase 18c next**: feed `ic_matrix.csv` + `cluster_winrate.csv` to `tools/feature_gate_proposal.py` to auto-draft `research/auto_feature_gates.yaml`.