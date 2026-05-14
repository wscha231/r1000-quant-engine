# Trade Insights Summary

- trades analyzed: **1044**
- generated: 2026-05-14 20:50 UTC

## 1. Signal IC by regime (rank correlation)
Top actionable findings:

**Worst signal x regime cells (potential gate candidates)**:
- `rs_acceleration_score` in **bear**: IC = -0.041
- `h6_dynamic_leader_score` in **bear**: IC = -0.038
- `h6_dynamic_leader_score` in **neutral**: IC = -0.028

**Best signal x regime cells (amplify candidates)**:
- `h6_dynamic_leader_score` in **bull**: IC = +0.162
- `rs_acceleration_score` in **bull**: IC = +0.146
- `theme_phase_multiplier_max` in **bull**: IC = +0.085

Full matrix in `ic_matrix.csv`.

## 2. Trade pattern clusters
**Worst pattern clusters (block candidates)**:
- cluster 6: win_rate=0.52, n=91, signature: h6_dynamic_leader_score=+1.93, selection_confirmation_score=+0.73, theme_phase_multiplier_primary=+0.54
- cluster 0: win_rate=0.53, n=146, signature: rs_acceleration_score=-1.33, selection_confirmation_score=+0.72, theme_phase_multiplier_max=+0.55

**Best pattern clusters (amplify candidates)**:
- cluster 1: win_rate=0.65, n=166, signature: portfolio_risk_entry_block_score=+2.13, portfolio_monster_early_score=+1.86, theme_phase_multiplier_max=-1.78
- cluster 2: win_rate=0.62, n=95, signature: h6_dynamic_leader_score=+2.12, rs_acceleration_score=+1.14, selection_confirmation_score=+0.73

Full table in `cluster_winrate.csv`.

## 3. SHAP / model importance
_(no SHAP - no data)_

---

**Phase 18c next**: feed `ic_matrix.csv` + `cluster_winrate.csv` to `tools/feature_gate_proposal.py` to auto-draft `research/auto_feature_gates.yaml`.