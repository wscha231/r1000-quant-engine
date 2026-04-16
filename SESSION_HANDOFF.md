# Session Handoff — 2026-04-17 09:30 KST

> **WHO AM I**: r1000 Quant Engine project (Russell 1000 Top-30 institutional).
> **PURPOSE OF THIS FILE**: shortest possible "pick-up-where-we-left-off" brief for a new Claude / Codex / GPT chat session on a different machine.
> **LIFETIME**: delete / rewrite this file whenever a phase is shipped or a new blocker appears. Do NOT let stale handoff notes accumulate — keep exactly one active handoff.

---

## 1. Last thing that happened

**Phase 4 / 5 / 6a / 6b / 6c all landed as separate commits. Phase 3 was REJECTED by A/B (see 28e41fe). Next action: user runs ONE FULL rebuild in Colab to pick up Phase 5 columns + measure each of the new phases.**

Timeline of recent commits on `origin/master`:

| Commit | Phase | Default | Summary |
|---|---|---|---|
| `28e41fe` | Phase 3 | **OFF (reject)** | A/B regression (-2.30pp CAGR, -0.13 Sharpe, -4.58pp MaxDD). Toggle kept for future re-eval. |
| `6b790cb` | Phase 4 | **OFF** | Regime-conditional sleeve multipliers. `SLEEVE_FACTOR_REGIME_MULTIPLIERS` table keyed on `event_regime_label`. Dual-gate: `regime_dynamic_sleeve_weights_enabled` + `PHASE_PHASE4_REGIME_WEIGHTS_ENABLED`. |
| `0756636` | Phase 5 | **ON** | Sub-industry leader/laggard. Three new columns (`industry_leader_gap`, `_bonus_score`, `_penalty_score`). Wired into all 3 sleeves. **`ENGINE_REUSE_VERSION` bumped -> `"2026-04-17-phase5-leader-laggard"` — forces next Colab run to FULL rebuild.** |
| `b4c63c9` | Phase 6a | **ON** | 3-level drawdown breaker (-8/-15/-25% -> cash 15/35/60%) with equity-based recovery hysteresis. Legacy single-threshold breaker preserved as fallback. |
| `4c3274d` | Phase 6b | **ON** | VIX level hard guard. 4 tiers (22/28/35/45 -> cash 10/25/40/55%). Inside `compute_regime_portfolio_controls`. |
| `ee93fa0` | Phase 6c | **OFF** | Volatility targeting (6m rolling vol, 12% target). Expressed as dynamic cash floor. Default OFF — user must explicitly opt in. |

Total: ~680 new lines across engine + CHANGELOG. Each phase has byte-identical legacy behavior when its toggle is off. 27 new EngineConfig fields total. All toggles are dual-gate (cfg + env).

---

## 2. What the user must do NEXT

**Run ONE FULL rebuild in Colab.** Required because Phase 5 bumped `ENGINE_REUSE_VERSION`, which invalidates the prior feature_store cache. This FULL rebuild simultaneously bakes Phase 5 columns into `feature_store_latest.parquet` AND measures the combined impact of Phase 5 + Phase 6a + Phase 6b running together (all default ON). Phase 4 and Phase 6c remain OFF in this run.

### Cell 2 config for the FULL rebuild

```python
QUICK_RESCORE_ONLY = False              # FULL rebuild required for Phase 5
OPTION_1_FULL_REBUILD = True
PHASE1_ALPHA_ENABLED = 'auto'           # keep ON
PHASE2_INDUSTRY_ENABLED = 'auto'        # keep ON
# Phase 3: rejected per 28e41fe — leave env unset (default OFF).
# Phase 4: default OFF (first measure 5/6a/6b baseline before layering 4).
# Phase 5: default ON.
# Phase 6a: default ON.
# Phase 6b: default ON.
# Phase 6c: default OFF.
```

Cell 3/4 unchanged.

Runtime: ~1.5-3h FULL rebuild.

### Post-run verification (in `outputs/scored_latest.csv` and `outputs/backtest_metrics.json`)

1. **Phase 5 columns populated**: `industry_leader_gap`, `industry_leader_bonus_score`, `industry_laggard_penalty_score` all have `nonzero_share >= 0.15` (bonus/penalty should be sparser than gap).
2. **Phase 6a diagnostics (in `equity_curve.csv`)**: `dd_breaker_multilevel_active = 1`, `dd_breaker_level` takes non-zero values during known drawdowns (2022-Q1, 2022-Q4).
3. **Phase 6b effect**: `cash_target` lifts during 2020-03 and 2023-SVB VIX spikes (compare to 2026-04-16 baseline run).
4. **Phase 4 verified OFF**: `regime_sleeve_multiplier_core == 1.0` on every row.
5. **Phase 3 verified OFF**: `sleeve_weight_renorm_active == 0.0`.
6. **Phase 6c verified OFF**: `vol_target_active == 0` on every row.
7. **Main portfolio metrics vs 2026-04-16 baseline** (`cagr=0.2010`, `sharpe=1.0754`, `max_dd=-0.2360`):
   - Phase 5 + 6a + 6b combined target: MaxDD improves >= 3pp, CAGR within ±0.5pp, Sharpe improves >= 0.05.

### Follow-up A/B measurements (QUICK_RESCORE ~20min each, optional but recommended)

After the FULL rebuild lands, these QUICK_RESCORE runs isolate each phase's marginal contribution vs the FULL-rebuild baseline (= Phase 5/6a/6b ON, Phase 4/6c OFF):

- **Phase 5 marginal**: set `PHASE_PHASE5_LEADER_LAGGARD_ENABLED=0`, keep others default -> isolate Phase 5 delta.
- **Phase 6a marginal**: `PHASE_PHASE6A_BREAKER_ENABLED=0` -> isolate Phase 6a.
- **Phase 6b marginal**: `PHASE_PHASE6B_VIX_ENABLED=0` -> isolate Phase 6b.
- **Phase 4 addition**: keep all defaults, ALSO set `PHASE_PHASE4_REGIME_WEIGHTS_ENABLED=1` + `cfg["regime_dynamic_sleeve_weights_enabled"]=True` -> measure Phase 4 on top.
- **Phase 6c addition**: similar for `PHASE_PHASE6C_VOLTARGET_ENABLED=1` + `cfg["volatility_targeting_enabled"]=True`.

Each A/B ships or doesn't ship based on the ship gate in `PHASE_ROADMAP.md` §3:

| Phase | Ship gate |
|---|---|
| 4 | Δ CAGR ≥ +0.5pp AND Δ Sharpe ≥ +0.05 |
| 5 | Δ CAGR ≥ +0.3pp AND future-sleeve hit-rate ↑ |
| 6a | Δ MaxDD ≤ -3pp AND Δ CAGR ≥ -0.5pp |
| 6b | Δ MaxDD ≤ -1pp in VIX-spike periods |
| 6c | Δ Sharpe ≥ +0.05 AND Δ CAGR ≥ -1pp |

---

## 3. What's next AFTER Phase 4/5/6 A/B measurements

- For any phase that PASSES its ship gate: flip its cfg default to True in a small commit, update CHANGELOG, push. No infra change needed — just `EngineConfig.xxx_enabled: bool = False` -> `True`.
- For any phase that FAILS: keep default OFF, record the negative result in CHANGELOG (mirror the 28e41fe Phase 3 rejection pattern).
- Once all Phase 4/5/6 A/B rulings are in, `SESSION_HANDOFF.md` gets rewritten with the new "last thing done + next action". At that point the immediate roadmap is exhausted — future work is proposal-driven (e.g. re-visit `PROPOSAL_defensive_upgrades.md` §2/4/5/6 which were skipped for the Phase 6 initial release).

---

## 4. Bootstrap prompt for a new chat session

Paste this into a fresh Claude chat on the new machine (or Colab) after cloning the repo:

```
I'm continuing work on the r1000 Quant Engine project. Before doing anything else, please:

1. Read `CLAUDE.md` — project basics.
2. Read `SESSION_HANDOFF.md` — current pending work (THIS is the most important file for picking up where we left off).
3. Read the last ~300 lines of `CHANGELOG.md` — most recent decisions (includes the Phase 3 rejection + Phase 4/5/6 implementations).
4. Read `PHASE_ROADMAP.md` §3 (PR plan) and §5 (invariants) — what's next.
5. Check `git log --oneline -8` to confirm the latest commit (should be at or after `ee93fa0 Add Phase 6c volatility targeting`).

Only after reading those files, ask me what I want to do next. Do NOT start editing anything until you've read them.

Context: Phases 4/5/6a/6b/6c are all implemented behind toggles. Phase 3 was rejected by A/B. Next action is one FULL rebuild in Colab to bake Phase 5 columns into feature_store and measure combined Phase 5/6a/6b impact; separate QUICK_RESCORE A/B runs after that to isolate each phase's marginal contribution.
```

---

## 5. Files that persist across machines

All source is in git, pushed to `origin/master`:

- `r1000_top30_institutional.py` — engine
- `r1000_data_collector.py` — collector
- `r1000_operator.py` — live operator layer
- `r1000_portfolio_state.py` — state persistence
- `colab_run.ipynb` — runbook
- `CLAUDE.md` — project brain (short)
- `PHASE_ROADMAP.md` — phase plan (long)
- `CHANGELOG.md` — decision log
- `SESSION_HANDOFF.md` — this file
- `PROPOSAL_defensive_upgrades.md` — Phase 6 design
- `PROPOSAL_growth_regime_offense_defense.md` — Phase 4 design reference

What's NOT in git (lives only on Google Drive):
- Drive repo mount: `/content/drive/MyDrive/r1000-quant-engine` (git clone of the repo)
- Drive data folder: `/content/drive/MyDrive/r1000_top30_institutional` (cache, outputs, companyfacts.zip, feature_store, models)

Cell A in Colab handles the split automatically: `git pull` the engine dir, `os.chdir` to the data dir.

---

## 6. How to delete this handoff

When all Phase 4/5/6 A/B rulings are shipped AND you've started the next initiative:

1. Replace this file's content with the new session handoff (new "last thing done" = all A/B rulings shipped, new "next action" = whatever comes next).
2. Never accumulate multiple handoff files. This is a single-item inbox, not a log.
