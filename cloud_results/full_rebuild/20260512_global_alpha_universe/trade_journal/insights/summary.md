# Trade Insights Summary

- trades analyzed: **912**
- generated: 2026-05-12 07:59 UTC

## 1. Signal IC by regime (rank correlation)
Top actionable findings:

**Worst signal x regime cells (potential gate candidates)**:
- `selection_confirmation_score` in **deep_bear**: IC = -0.412
- `theme_phase_multiplier_primary` in **deep_bear**: IC = -0.386
- `h6_dynamic_leader_score` in **deep_bear**: IC = -0.247

**Best signal x regime cells (amplify candidates)**:
- `rs_acceleration_score` in **deep_bear**: IC = +0.262
- `theme_phase_multiplier_max` in **bull**: IC = +0.102
- `rs_acceleration_score` in **neutral**: IC = +0.075

Full matrix in `ic_matrix.csv`.

## 2. Trade pattern clusters
**Worst pattern clusters (block candidates)**:
- cluster 0: win_rate=0.53, n=49, signature: portfolio_risk_entry_block_score=+3.34, portfolio_monster_early_score=+1.98, theme_phase_multiplier_max=-1.76
- cluster 7: win_rate=0.57, n=70, signature: theme_phase_multiplier_max=-1.76, theme_phase_multiplier_primary=-1.76, selection_confirmation_score=-1.58

**Best pattern clusters (amplify candidates)**:
- cluster 3: win_rate=0.66, n=96, signature: portfolio_monster_early_score=+1.81, theme_phase_multiplier_max=-1.76, theme_phase_multiplier_primary=-1.76
- cluster 6: win_rate=0.59, n=140, signature: rs_acceleration_score=+0.87, theme_phase_multiplier_max=+0.56, theme_phase_multiplier_primary=+0.56

Full table in `cluster_winrate.csv`.

## 3. SHAP / model importance
_(no SHAP - no data)_

---

**Phase 18c next**: feed `ic_matrix.csv` + `cluster_winrate.csv` to `tools/feature_gate_proposal.py` to auto-draft `research/auto_feature_gates.yaml`.