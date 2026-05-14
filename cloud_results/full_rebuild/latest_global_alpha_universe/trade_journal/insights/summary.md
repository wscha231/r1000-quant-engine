# Trade Insights Summary

- trades analyzed: **965**
- generated: 2026-05-14 11:54 UTC

## 1. Signal IC by regime (rank correlation)
Top actionable findings:

**Worst signal x regime cells (potential gate candidates)**:
- `theme_phase_multiplier_primary` in **bull**: IC = -0.053
- `rs_acceleration_score` in **bear**: IC = -0.038
- `h6_dynamic_leader_score` in **bear**: IC = -0.034

**Best signal x regime cells (amplify candidates)**:
- `rs_acceleration_score` in **bull**: IC = +0.116
- `h6_dynamic_leader_score` in **bull**: IC = +0.089
- `rs_acceleration_score` in **neutral**: IC = +0.071

Full matrix in `ic_matrix.csv`.

## 2. Trade pattern clusters
**Worst pattern clusters (block candidates)**:
- cluster 6: win_rate=0.49, n=79, signature: selection_confirmation_score=-0.99, rs_acceleration_score=-0.73, entry_quality_score=-0.61
- cluster 0: win_rate=0.50, n=62, signature: theme_phase_multiplier_max=-1.89, theme_phase_multiplier_primary=-1.89, selection_confirmation_score=-1.61

**Best pattern clusters (amplify candidates)**:
- cluster 1: win_rate=0.69, n=100, signature: h6_dynamic_leader_score=+1.98, rs_acceleration_score=+0.98, selection_confirmation_score=+0.70
- cluster 3: win_rate=0.62, n=143, signature: portfolio_risk_entry_block_score=+2.23, portfolio_monster_early_score=+1.98, theme_phase_multiplier_max=-1.89

Full table in `cluster_winrate.csv`.

## 3. SHAP / model importance
_(no SHAP - no data)_

---

**Phase 18c next**: feed `ic_matrix.csv` + `cluster_winrate.csv` to `tools/feature_gate_proposal.py` to auto-draft `research/auto_feature_gates.yaml`.