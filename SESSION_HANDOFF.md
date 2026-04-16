# Session Handoff — 2026-04-17 12:30 KST

> **WHO AM I**: r1000 Quant Engine project (Russell 1000 Top-30 institutional).
> **PURPOSE OF THIS FILE**: shortest possible "pick-up-where-we-left-off" brief for a new Claude / Codex / GPT chat session on a different machine.
> **LIFETIME**: delete / rewrite this file whenever a phase is shipped or a new blocker appears. Do NOT let stale handoff notes accumulate — keep exactly one active handoff.

---

## 0. TL;DR — one-paragraph resume brief

A 2026-04-17 morning FULL rebuild exposed a regression: main-portfolio CAGR dropped 20.10% → 15.44% (−4.66pp), Sharpe 1.08 → 0.84, MaxDD −23.6% → −26.3%, IR 0.58 → 0.20. Root cause: Phase 5's sub-industry leader/laggard bonus fires on only 3.6% of rows / penalty on 0%, but `row_mean` was treating those zero-valued z-scores as valid terms, diluting every other factor's effective weight by ~6% across all three sleeves (same trap Phase 3 tried to solve). The fix (commit `c4d50fd`) masks zero-valued signals to NaN so `row_mean` drops them from BOTH numerator and denominator. A companion fix extends `equity_curve.csv` to carry Phase 6a/6c diagnostic columns so the user can verify breaker activity. Current HEAD = `c4d50fd`. **Next action: Colab QUICK_RESCORE (~20 min) to verify CAGR recovery toward baseline.** Post-recovery, decide whether Phase 5 ON-by-default is worth keeping (likely small positive contribution once dilution is gone), then run the three deferred A/Bs (Phase 4 regime weights, Phase 6c vol-target, Phase 7a insider+accruals).

---

## 1. Recent timeline on `origin/master` (newest first)

| Commit | Title | Default state | Notes |
|---|---|---|---|
| `c4d50fd` | **Fix Phase 5 row_mean dilution + restore breaker diagnostic CSV export** | — | Emergency fix. Phase 5 ON stays ON but now actually acts like ON (no dilution). Diagnostic columns now flow to CSV. |
| `914558f` | Add Phase 7a insider-flow + accruals sleeve wiring | **OFF** | dual-gate opt-in. Expected +0.3-0.6pp CAGR once wired. Not yet A/B-measured. |
| `017b853` | Refresh agent-facing docs after Phase 4/5/6 rollout | — | Pure docs refresh. |
| `f7ec511` | Align Phase 6a/6b getattr defaults with EngineConfig defaults | — | Pure hardening. No behaviour change in active paths. |
| `33ed065` | Wire Phase 4/5/6 toggles into Colab notebook + rotate SESSION_HANDOFF | — | Cell 2 gained 6 new phase env toggles. |
| `ee93fa0` | Add Phase 6c volatility targeting | **OFF** | Dynamic cash-floor expression. Default OFF per plan. |
| `4c3274d` | Add Phase 6b VIX level hard guard | **ON** | 4-tier cash floor on VIX ≥ 22/28/35/45. |
| `b4c63c9` | Add Phase 6a 3-level drawdown circuit breaker | **ON** | −8/−15/−25% ladder + equity-based recovery hysteresis. |
| `0756636` | Add Phase 5 sub-industry leader/laggard | **ON** | Bumped `ENGINE_REUSE_VERSION` to `"2026-04-17-phase5-leader-laggard"`. |
| `6b790cb` | Add Phase 4 regime-conditional sleeve multipliers | **OFF** | A/B pending. |
| `28e41fe` | **Record Phase 3 A/B rejection** | **OFF (reject)** | ΔCAGR −2.30pp / ΔSharpe −0.13 / ΔMaxDD −4.58pp. Infra retained, do not re-try without `l1_target` redesign. |

Full chronological detail is in `CHANGELOG.md` (last ~400 lines). `PHASE_ROADMAP.md` §3 carries the PR-level status table.

---

## 2. What the user must do NEXT — **Colab QUICK_RESCORE**

Goal: confirm the `c4d50fd` dilution fix restores the main-portfolio CAGR toward the 2026-04-16 baseline (CAGR 20.10%, Sharpe 1.08, MaxDD −23.60%). Runtime ~15-25 min (QUICK_RESCORE reuses feature_store + trained models).

### Cell A — sync code + switch cwd (paste at top of notebook, every session)

```python
import subprocess, sys, os
REPO_DIR = '/content/drive/MyDrive/r1000-quant-engine'
DATA_DIR = '/content/drive/MyDrive/r1000_top30_institutional'
subprocess.run(['git', '-C', REPO_DIR, 'fetch', 'origin', 'master'], check=True)
subprocess.run(['git', '-C', REPO_DIR, 'reset', '--hard', 'origin/master'], check=True)
print("Latest 3 commits on origin/master:")
subprocess.run(['git', '-C', REPO_DIR, 'log', '--oneline', '-3'])
# Expected HEAD: c4d50fd "Fix Phase 5 row_mean dilution ..."
if REPO_DIR not in sys.path:
    sys.path.insert(0, REPO_DIR)
os.chdir(DATA_DIR)
print("\ncwd:", os.getcwd())
```

### Cell 2 — toggles (critical: QUICK_RESCORE_ONLY=True this time, not FULL)

```python
QUICK_RESCORE_ONLY = True              # ★ QUICK_RESCORE, NOT full rebuild
OPTION_1_FULL_REBUILD = False
FRESH_START = False
NUKE_ALL = False

# All phase toggles left at 'auto' — cfg defaults are:
#   Phase 1 ON, Phase 2 ON, Phase 3 OFF, Phase 4 OFF,
#   Phase 5 ON, Phase 6a ON, Phase 6b ON, Phase 6c OFF,
#   Phase 7a OFF.
# The dilution fix applies automatically — no env override needed.
```

### Cell 3 → Cell 4 (pipeline, ~15-25 min in QUICK_RESCORE mode)

Run the notebook's existing collector + pipeline cells unchanged.

### Cell E — recovery verdict (run after Cell 4 finishes)

```python
import json, pathlib
import pandas as pd

BASE = pathlib.Path('/content/drive/MyDrive/r1000_top30_institutional')

# 1. Phase 5 signal coverage
scored = pd.read_csv(BASE / 'outputs/scored_latest.csv', low_memory=False)
print("=" * 70); print("1. PHASE 5 SIGNAL COVERAGE (should be unchanged vs prior run — the fix is in the sleeve-composition weighting, not in the signal production)"); print("=" * 70)
for col in ['industry_leader_gap', 'industry_leader_bonus_score', 'industry_laggard_penalty_score']:
    if col in scored.columns:
        v = pd.to_numeric(scored[col], errors='coerce').fillna(0.0)
        print(f"  {col}: nonzero_share = {(v != 0).mean():.2%}, mean = {v.mean():.4f}, max = {v.max():.4f}")

# 2. equity_curve.csv should now carry Phase 6a diagnostic columns
eq = pd.read_csv(BASE / 'outputs/equity_curve.csv')
print(); print("=" * 70); print("2. equity_curve.csv diagnostic columns (post-fix)"); print("=" * 70)
p6_cols = [c for c in eq.columns if 'dd_breaker' in c or 'vol_target' in c or 'drawdown_circuit' in c]
print(f"  Total columns: {len(eq.columns)}")
print(f"  Phase 6-related columns now present: {p6_cols}")
if 'dd_breaker_level' in eq.columns:
    print(f"  dd_breaker_level distribution: {eq['dd_breaker_level'].value_counts().to_dict()}")
    print(f"  dd_breaker_multilevel_active mean: {eq['dd_breaker_multilevel_active'].mean():.4f}")

# 3. MAIN PORTFOLIO METRICS vs baseline
print(); print("=" * 70); print("3. RECOVERY vs 2026-04-16 baseline"); print("=" * 70)
bm = json.loads((BASE / 'outputs/backtest_metrics.json').read_text())
baseline = {'cagr': 0.2010, 'sharpe': 1.0754, 'max_dd': -0.2360, 'ir': 0.5835, 'excess_cagr': 0.0660, 'avg_stock_names': 25.78}
print(f"  {'metric':24s} {'new':>10s} {'baseline':>10s} {'delta':>14s}")
for k in ['cagr', 'sharpe', 'max_dd', 'ir', 'excess_cagr', 'avg_stock_names', 'vol_ann', 'beat_month_ratio']:
    new_v = bm.get(k, float('nan'))
    bl_v = baseline.get(k)
    if bl_v is not None:
        if k in ['cagr', 'max_dd', 'excess_cagr']:
            d_str = f"{(new_v - bl_v) * 100:+.2f}pp"
        else:
            d_str = f"{new_v - bl_v:+.4f}"
        print(f"  {k:24s} {new_v:>10.4f} {bl_v:>10.4f} {d_str:>14s}")
    else:
        print(f"  {k:24s} {new_v:>10.4f}")

# 4. SHIP GATE (ratcheted to the 2026-04-16 baseline — we just need the regression undone)
print(); print("=" * 70); print("4. VERDICT"); print("=" * 70)
dCAGR = (bm['cagr'] - baseline['cagr']) * 100
dSharpe = bm['sharpe'] - baseline['sharpe']
dMaxDD = (bm['max_dd'] - baseline['max_dd']) * 100
print(f"  ΔCAGR   = {dCAGR:+.2f}pp  | acceptable >= -1.0pp")
print(f"  ΔSharpe = {dSharpe:+.4f}  | acceptable >= -0.05")
print(f"  ΔMaxDD  = {dMaxDD:+.2f}pp  | acceptable >= -1.0pp")
print()
if dCAGR >= -1.0 and dSharpe >= -0.05 and dMaxDD >= -1.0:
    print("  -> ✅ REGRESSION RECOVERED. Phase 5 default-ON is safe. Next: run Phase 5 ON-vs-OFF A/B to measure its marginal alpha.")
elif dCAGR >= -3.0:
    print("  -> ⚠️  PARTIAL RECOVERY. Dilution fix helped but something else is still leaking ~1-3pp CAGR. Flip cfg.sub_industry_leader_laggard_enabled=False and re-run QUICK_RESCORE to isolate.")
else:
    print("  -> ❌ STILL BROKEN. Roll back more phases: set PHASE_PHASE5_LEADER_LAGGARD_ENABLED=0, PHASE_PHASE6A_BREAKER_ENABLED=0, PHASE_PHASE6B_VIX_ENABLED=0 in Cell 2 and re-run. Report which subset triggers the drop.")
```

**Paste the full output of Cell E back into the chat when it finishes.** The verdict line determines the next action.

---

## 3. Decision tree after the QUICK_RESCORE

### 3a. If verdict = ✅ REGRESSION RECOVERED

1. Run **Phase 5 marginal A/B**: set `PHASE_PHASE5_LEADER_LAGGARD_ENABLED=0` in Cell 2, re-run QUICK_RESCORE (20 min). Compare ON-vs-OFF metrics. If Phase 5 adds ≥ +0.3pp CAGR, ship (flip default stays True, write ship-confirmation CHANGELOG entry). If neutral / negative, flip `cfg.sub_industry_leader_laggard_enabled=False` as the new default.
2. Run **Phase 4 A/B**: set `PHASE_PHASE4_REGIME_WEIGHTS_ENABLED=1` + `cfg["regime_dynamic_sleeve_weights_enabled"]=True` in `COMMON_CFG_OVERRIDES`. Ship gate: ΔCAGR ≥ +0.5pp AND ΔSharpe ≥ +0.05.
3. Run **Phase 7a A/B**: set `PHASE_PHASE7A_INSIDER_ACCRUALS_ENABLED=1` + `cfg["phase7a_insider_accruals_enabled"]=True`. Ship gate: ΔCAGR ≥ +0.3pp, ΔSharpe ≥ +0.02, MaxDD not worse by +1pp.
4. Run **Phase 6c A/B**: set `PHASE_PHASE6C_VOLTARGET_ENABLED=1` + `cfg["volatility_targeting_enabled"]=True`. Ship gate: ΔSharpe ≥ +0.05 AND ΔCAGR ≥ −1pp.

Each A/B is ~20 min in QUICK_RESCORE. Total ~80 min for all four.

### 3b. If verdict = ⚠️ PARTIAL RECOVERY

Flip cfg.sub_industry_leader_laggard_enabled to False via `COMMON_CFG_OVERRIDES["sub_industry_leader_laggard_enabled"] = False`, re-run QUICK_RESCORE. If recovery completes, Phase 5 default should land as OFF in a small commit. Then proceed through 3a steps 2-4.

### 3c. If verdict = ❌ STILL BROKEN

Isolate which phase is the culprit. In Cell 2:

```python
os.environ["PHASE_PHASE5_LEADER_LAGGARD_ENABLED"] = "0"
os.environ["PHASE_PHASE6A_BREAKER_ENABLED"] = "0"
os.environ["PHASE_PHASE6B_VIX_ENABLED"] = "0"
```

Re-run QUICK_RESCORE. That should recover to the 2026-04-16 baseline. Then turn them back on one at a time (each a separate 20-min QUICK run) to find the offender.

---

## 4. Bootstrap prompt for a fresh chat session (office PC, phone, anywhere)

Paste this into a new Claude / Codex / GPT chat:

```
I'm continuing work on the r1000 Quant Engine project. Before doing anything else, please:

1. Read `CLAUDE.md` — project basics.
2. Read `SESSION_HANDOFF.md` — current pending work (THIS is the most important file for picking up where we left off).
3. Read the last ~300 lines of `CHANGELOG.md` — most recent decisions.
4. Read `PHASE_ROADMAP.md` §3 (PR plan) and §5 (invariants) — what's next.
5. Check `git log --oneline -5` to confirm the latest commit is at or after `c4d50fd Fix Phase 5 row_mean dilution + restore breaker diagnostic CSV export`.

Only after reading those files, ask me what I want to do next. Do NOT start editing anything until you've read them.

Context: a 2026-04-17 FULL rebuild exposed a Phase 5 row_mean dilution regression (CAGR 20.10% → 15.44%). The fix landed in commit c4d50fd and the immediate next action is a Colab QUICK_RESCORE (~20 min) to verify CAGR recovery. Section 2 of SESSION_HANDOFF.md has the exact cells to paste into Colab and the recovery-verdict cell.
```

---

## 5. Files that persist across machines

Everything source-of-truth is in git on `origin/master`:

- `r1000_top30_institutional.py` — engine (~26k lines)
- `r1000_data_collector.py` — collector
- `r1000_operator.py` — live operator layer
- `r1000_portfolio_state.py` — state persistence
- `colab_run.ipynb` — runbook (Cell 2 already has all 8 phase env toggles)
- `CLAUDE.md` — project brain (short)
- `PHASE_ROADMAP.md` — phase plan with DONE/REJECTED/PLANNED status
- `CHANGELOG.md` — decision log (every commit has a matching entry under the Agent Update Contract format)
- `SESSION_HANDOFF.md` — this file; rewritten whenever a phase ships or a new blocker appears
- `PROPOSAL_defensive_upgrades.md` — Phase 6 design (§2, §4, §5, §6 still open)
- `PROPOSAL_growth_regime_offense_defense.md` — Phase 4 design reference

What's NOT in git (lives only on Google Drive):

- `/content/drive/MyDrive/r1000-quant-engine/` — Cell A keeps this `git reset --hard origin/master` on every run so it's always the live repo.
- `/content/drive/MyDrive/r1000_top30_institutional/` — data folder with `cache_*/`, `feature_store/`, `checkpoints/`, `outputs/`, `companyfacts.zip`. This is where the engine reads/writes. Cell A `os.chdir()`'s into it.

Any machine with (a) a clone of the repo and (b) the Drive mounted has full state. No additional setup needed at the office — just open `colab_run.ipynb` from Drive.

---

## 6. Quick reference — Phase status + toggles

| Phase | cfg field | env var | Default | A/B status |
|---|---|---|---|---|
| 1 | (no flag — always on via `phase_is_enabled` only) | `PHASE_PHASE1_ALPHA_ENABLED` | ON | Shipped pre-2026-04-16 |
| 2 | (no flag) | `PHASE_PHASE2_INDUSTRY_ENABLED` | ON | Shipped 2026-04-16 (keepcols-fix verified) |
| 3 | `sleeve_weight_renorm_enabled` | `PHASE_PHASE3_RENORM_ENABLED` | **OFF (reject)** | ❌ A/B regressed. Infra retained for future re-design. |
| 4 | `regime_dynamic_sleeve_weights_enabled` | `PHASE_PHASE4_REGIME_WEIGHTS_ENABLED` | OFF | A/B pending. Ship gate +0.5pp CAGR + 0.05 Sharpe. |
| 5 | `sub_industry_leader_laggard_enabled` | `PHASE_PHASE5_LEADER_LAGGARD_ENABLED` | ON | A/B pending (dilution fix in c4d50fd). Real marginal contribution unknown. |
| 6a | `drawdown_breaker_multilevel_enabled` | `PHASE_PHASE6A_BREAKER_ENABLED` | ON | Defensive A/B pending. Ship gate ΔMaxDD ≤ −3pp. |
| 6b | `vix_level_guard_enabled` | `PHASE_PHASE6B_VIX_ENABLED` | ON | Defensive A/B pending. Ship gate ΔMaxDD ≤ −1pp on VIX-spike months. |
| 6c | `volatility_targeting_enabled` | `PHASE_PHASE6C_VOLTARGET_ENABLED` | OFF | A/B pending. Ship gate ΔSharpe ≥ +0.05. |
| 7a | `phase7a_insider_accruals_enabled` | `PHASE_PHASE7A_INSIDER_ACCRUALS_ENABLED` | OFF | A/B pending. Ship gate ΔCAGR ≥ +0.3pp. |

Toggle weights tunable via `COMMON_CFG_OVERRIDES` in Colab Cell 2:
- Phase 7a: `phase7a_insider_early_weight` (0.25), `phase7a_insider_future_weight` (0.15), `phase7a_accruals_core_weight` (−0.20).
- Phase 4: `regime_sleeve_multiplier_table` (None → use built-in 6-regime table).

---

## 7. How to rotate this handoff

When:
- **QUICK_RESCORE recovers the regression AND** a phase A/B ships (or all pending phases have been measured and decided) → replace §1/§2/§3 with the new state.
- **Regression is NOT recovered** → §2 becomes "investigate further" with the isolation cells from §3c.

Never accumulate multiple handoff files. This is a single-item inbox, not a log.
