# Session Handoff — 2026-04-17 11:42 KST

> **WHO AM I**: r1000 Quant Engine project (Russell 1000 Top-30 institutional).
> **PURPOSE OF THIS FILE**: shortest possible "pick-up-where-we-left-off" brief for a new Claude / Codex / GPT chat session on a different machine.
> **LIFETIME**: delete / rewrite this file whenever a phase ships or a new blocker appears. One active handoff only.

---

## 0. TL;DR — one-paragraph resume brief

A morning Phase C diagnosis (commit `027c5b3`) measured factor IC across 83 OOS months using the Drive's `scored_oos_latest.parquet` and found (a) only 9% of 258 factors have real alpha, 59% are pure noise, 12 have negative IC; (b) the final `score` has +0.011 IC at r_1m but **-0.006 at r_12m** — the engine is structurally wired for short-term flips, not multi-year winners; (c) fundamental factors (ep_ttm, fcfy_ttm, sp_ttm, sage_composite) have 2-4x stronger IC at r_12m than r_1m; (d) NVDA was ranked 9 → 17 → 18 → 23 during its biggest AI-boom months and popped to rank 1 only AFTER the parabolic move; (e) a 2024-06 `labor_softening_score = -2e14` corruption propagated to all 600 stock scores that month. The afternoon Phase 8 implementation (commits `4cd938e` → `caddec3`) shipped all ten recommended changes from `PHASE_8_PROPOSAL.md`. A pre-FULL-rebuild code review (commit `300affc`) caught and fixed two CRITICAL bugs: (1) `weighted_sleeve_composite` was not actually dropping weight-0 pairs (silently diluted by 1/N instead), defeating Phase 8a/b/c toggles; and (2) `hold_persistence_bonus` was using `r_1m` which is the FORWARD return (lookahead bias), swapped to `mom_1m` (backward 21-day realised return). Current HEAD = `300affc`. **Next action: Colab FULL REBUILD (~3h) with all Phase 8 toggles at default ON, then Cell E recovery-verdict comparing new metrics against the 2026-04-16 baseline (CAGR 20.10%, Sharpe 1.08, MaxDD -23.60%).** Ship gate: CAGR ≥ 25%.

---

## 1. Recent timeline on `origin/master` (newest first)

| Commit | Title | Phase | Requires | Default |
|---|---|---|---|---|
| `300affc` | **Phase 8 review fixes: weight-0 skip + r_1m lookahead fix** | review | no rebuild | always-on |
| `caddec3` | Phase 8c: Mega-cap future override + growth-adj valuation | 8c.1 + 8c.2 | QUICK-measurable | ON |
| `3e44d35` | **Phase 8b.1: Long-lookback momentum (mom_18m/24m/36m + multi_year_winner)** | 8b.1 | **FULL rebuild** | ON |
| `e3bf29d` | Phase 8a.4: Hold persistence bonus to reduce turnover | 8a.4 | QUICK-measurable | ON |
| `3624e06` | Phase 8a.1 + 8a.2: Drop 3 negative-IC factors + disable Phase 5 default | 8a.1 / 8a.2 | QUICK-measurable | ON / OFF |
| `4cd938e` | Phase 8a safety: rolling_robust_z MAD floor + macro clamp + Phase 1 keepcols | 8a.5 + 8b.3 | **FULL rebuild** | always-on |
| `027c5b3` | **Phase C diagnosis docs (factor IC, counterfactuals, bugs, Phase 8 proposal)** | C | — | — |
| `53e8c91` | Rotate SESSION_HANDOFF for office-resume after dilution fix | — | — | — |
| `c4d50fd` | Fix Phase 5 row_mean dilution + restore breaker diagnostic CSV export | — | QUICK | — |

**Current `ENGINE_REUSE_VERSION`**: `"2026-04-17-phase8b-long-lookback-momentum"`. FULL rebuild required because the feature-store schema grew by 10 columns (5 Phase 1 + 5 Phase 8b).

See `DIAGNOSIS_FACTOR_IC.md`, `DIAGNOSIS_COUNTERFACTUAL.md`, `DIAGNOSIS_BUGS.md`, `PHASE_8_PROPOSAL.md` for the data-driven justification behind every Phase 8 change.

---

## 2. What the user must do NEXT — **Colab FULL REBUILD**

Goal: measure the combined CAGR effect of Phase 8a + 8b + 8c. Runtime ~3 hours (FULL rebuild: feature_store regeneration + walk-forward retrain). All 10 Phase 8 changes are at their default ON setting, so no env overrides needed.

### Cell A — sync code + switch cwd (paste at top of notebook every session)

```python
import subprocess, sys, os
REPO_DIR = '/content/drive/MyDrive/r1000-quant-engine'
DATA_DIR = '/content/drive/MyDrive/r1000_top30_institutional'
subprocess.run(['git', '-C', REPO_DIR, 'fetch', 'origin', 'master'], check=True)
subprocess.run(['git', '-C', REPO_DIR, 'reset', '--hard', 'origin/master'], check=True)
print("Latest 5 commits on origin/master:")
subprocess.run(['git', '-C', REPO_DIR, 'log', '--oneline', '-5'])
# Expected HEAD: 300affc "Phase 8 review fixes: weight-0 skip + r_1m lookahead fix"
if REPO_DIR not in sys.path:
    sys.path.insert(0, REPO_DIR)
os.chdir(DATA_DIR)
print("\ncwd:", os.getcwd())
```

### Cell 2 — toggles (critical: FULL rebuild, not QUICK)

```python
QUICK_RESCORE_ONLY = False             # ★ FULL rebuild this time
OPTION_1_FULL_REBUILD = True           # ★ required
FRESH_START = False
NUKE_ALL = False

# All Phase 8 toggles left at 'auto' — cfg defaults are:
#   Phase 8a.1 negative-IC drop:           ON
#   Phase 8a.2 Phase 5 disabled:           OFF (by default, i.e. Phase 5 off)
#   Phase 8a.4 hold persistence:           ON
#   Phase 8a.5 macro clamp:                always-on (no toggle)
#   Phase 8b.1 long-lookback momentum:     ON
#   Phase 8b.3 Phase 1 keepcols:           always-on (no toggle)
#   Phase 8c.1 megacap future override:    ON
#   Phase 8c.2 growth-adj valuation:       ON
# No env overrides needed. Let cfg defaults drive the run.
```

### Cell 3 → Cell 4 (pipeline, ~2.5-3.5h in FULL mode)

Run the notebook's existing collector + pipeline cells unchanged. Expect:
- Cell 3 (collector): ~10-20 min (mostly cached; new feature coverage is price-based which is already cached)
- Cell 4 (pipeline): ~2.5-3h for FULL rebuild + walk-forward + latest scoring

### Cell E — recovery verdict (run after Cell 4 finishes)

```python
import json, pathlib
import pandas as pd

BASE = pathlib.Path('/content/drive/MyDrive/r1000_top30_institutional')

print("=" * 70); print("1. PHASE 8 COLUMN COVERAGE (verify keepcols fix + new Phase 8b features)"); print("=" * 70)
scored = pd.read_csv(BASE / 'outputs/scored_latest.csv', low_memory=False)
phase8_cols = [
    # Phase 1 keepcols fix — MUST now be present with non-zero coverage
    'fundamental_turnaround_acceleration_score', 'cashflow_inflection_under_loss_score',
    'value_inflection_score', 'uptrend_continuation_score', 'uptrend_breakdown_penalty',
    # Phase 8b long-lookback — NEW features
    'mom_18m', 'mom_24m', 'mom_36m', 'multi_year_winner_score', 'persistence_trend_24m',
    # Phase 8a.4 / 8b / 8c diagnostics
    'hold_persistence_bonus', 'phase8a_hold_persistence_active',
    'phase8b_long_lookback_active', 'phase8c_megacap_override_active',
    'phase8c_growth_adj_valuation_active',
]
for c in phase8_cols:
    if c in scored.columns:
        v = pd.to_numeric(scored[c], errors='coerce').fillna(0.0)
        print(f"  {c:52s}: nonzero={(v != 0).mean():>7.1%}  mean={v.mean():>+.4f}")
    else:
        print(f"  {c:52s}: MISSING")

print(); print("=" * 70); print("2. MAIN PORTFOLIO METRICS vs 2026-04-16 baseline"); print("=" * 70)
bm = json.loads((BASE / 'outputs/backtest_metrics.json').read_text())
baseline = {'cagr': 0.2010, 'sharpe': 1.0754, 'max_dd': -0.2360, 'ir': 0.5835, 'excess_cagr': 0.0660, 'avg_stock_names': 25.78, 'avg_turnover_monthly': 0.4951}
print(f"  {'metric':24s} {'new':>10s} {'baseline':>10s} {'delta':>14s}")
for k in ['cagr', 'sharpe', 'max_dd', 'ir', 'excess_cagr', 'avg_stock_names', 'vol_ann', 'beat_month_ratio', 'avg_turnover_monthly']:
    new_v = bm.get(k, float('nan'))
    bl_v = baseline.get(k)
    if bl_v is not None:
        d_str = f"{(new_v - bl_v) * 100:+.2f}pp" if k in ['cagr', 'max_dd', 'excess_cagr', 'avg_turnover_monthly'] else f"{new_v - bl_v:+.4f}"
        print(f"  {k:24s} {new_v:>10.4f} {bl_v:>10.4f} {d_str:>14s}")
    else:
        print(f"  {k:24s} {new_v:>10.4f}")

print(); print("=" * 70); print("3. PHASE 8 VERDICT"); print("=" * 70)
dCAGR = (bm['cagr'] - baseline['cagr']) * 100
dSharpe = bm['sharpe'] - baseline['sharpe']
dMaxDD = (bm['max_dd'] - baseline['max_dd']) * 100
dTurnover = (bm['avg_turnover_monthly'] - baseline['avg_turnover_monthly']) * 100
print(f"  CAGR      new={bm['cagr']*100:+.2f}%  (target >=25%, stretch 30%+)")
print(f"  Sharpe    new={bm['sharpe']:.4f}    (target >=1.00)")
print(f"  MaxDD     new={bm['max_dd']*100:+.2f}% (target better than -24%)")
print(f"  Turnover  new={bm['avg_turnover_monthly']*100:+.2f}%/mo (target <35%/mo)")
print()
if bm['cagr'] >= 0.25 and bm['sharpe'] >= 1.0:
    print("  -> SHIP. Phase 8 at default ON is the new baseline.")
elif bm['cagr'] >= 0.22:
    print("  -> PARTIAL SHIP. CAGR target missed but directionally positive. Run A/B isolation below.")
else:
    print("  -> REGRESSION. Set PHASE_PHASE8A_NEG_IC_DROP=0, PHASE_PHASE8B_LONG_LOOKBACK_ENABLED=0,")
    print("     PHASE_PHASE8C_MEGACAP_OVERRIDE=0, PHASE_PHASE8C_GROWTH_ADJ_VALUATION=0")
    print("     and re-run QUICK_RESCORE. Compare to isolate offender.")
```

**Paste the full output of Cell E back into the chat when Cell 4 finishes.** The CAGR / Sharpe / MaxDD numbers + Phase 8 column coverage determine the next action.

---

## 3. Decision tree after FULL rebuild

### 3a. If CAGR ≥ 25% AND Sharpe ≥ 1.0 (SHIP)

1. Update `backtest_metrics.json` baseline in a new CHANGELOG entry: "phase8-shipped-ab-sweep-start".
2. Commit `colab_run.ipynb` Cell 2 unchanged (defaults already correct).
3. **Plan Phase 8d/8e** (deferred items from `PHASE_8_PROPOSAL.md`):
   - Phase 8d: IC-proportional sleeve reweighting (requires correlation audit first)
   - Phase 8e: r_12m ML training target (requires walk-forward refactor — medium risk)
4. Consider tightening Phase 8c.1 mega-cap override criteria if too many names are being force-reclassified (check `phase8c_megacap_override_active` distribution in `scored_latest.csv`).

### 3b. If CAGR in [18%, 25%) (PARTIAL)

Run four QUICK_RESCORE A/B runs (each ~20 min) flipping ONE Phase 8 env var off at a time:

```python
# Run A (negative-IC drop off)
os.environ["PHASE_PHASE8A_NEG_IC_DROP"] = "0"

# Run B (hold persistence off)
os.environ["PHASE_PHASE8A_HOLD_PERSISTENCE"] = "0"

# Run C (megacap override off)
os.environ["PHASE_PHASE8C_MEGACAP_OVERRIDE"] = "0"

# Run D (growth-adj valuation off)
os.environ["PHASE_PHASE8C_GROWTH_ADJ_VALUATION"] = "0"
```

Whichever A/B shows the biggest NEGATIVE CAGR delta (vs. the all-ON baseline) is the strongest contributing phase — keep it ON. Whichever shows positive delta is a candidate for default OFF (or tuning).

Note: Phase 8b.1 requires FULL rebuild to A/B so it's last to test.

### 3c. If CAGR < 18% (REGRESSION)

1. First check Cell E §1 output: are any Phase 1 / 8b columns still MISSING? If so the keepcols-fix didn't take — verify `git log --oneline` shows `caddec3` or newer.
2. If columns are populated but CAGR regressed, disable phases in this order via env:
   - `PHASE_PHASE8B_LONG_LOOKBACK_ENABLED=0` (biggest change, most likely to break)
   - `PHASE_PHASE8C_MEGACAP_OVERRIDE=0` (concentration risk)
   - `PHASE_PHASE8A_NEG_IC_DROP=0` (if 83-month IC sample was unrepresentative)
3. Re-run QUICK_RESCORE after each toggle to isolate.
4. Report the isolation result — the phase that, when disabled, recovers CAGR most is the culprit. Likely cause: factor correlation the simulation didn't capture.

---

## 4. Bootstrap prompt for a fresh chat session (office PC, phone, anywhere)

Paste this into a new Claude / Codex / GPT chat:

```
I'm continuing work on the r1000 Quant Engine project. Before doing anything else, please:

1. Read `CLAUDE.md` — project basics.
2. Read `SESSION_HANDOFF.md` — current pending work (THIS is the most important file for picking up where we left off).
3. Read the last ~400 lines of `CHANGELOG.md` — most recent decisions (Phase 8 restructuring entries).
4. Read `PHASE_8_PROPOSAL.md` — the proposal doc behind the Phase 8 commits.
5. Read `DIAGNOSIS_FACTOR_IC.md`, `DIAGNOSIS_COUNTERFACTUAL.md`, `DIAGNOSIS_BUGS.md` — data evidence supporting Phase 8.
6. Check `git log --oneline -10` to confirm the latest commit is at or after `300affc Phase 8 review fixes: weight-0 skip + r_1m lookahead fix`.

Only after reading those files, ask me what I want to do next. Do NOT start editing anything until you've read them.

Context: Phase 8 (the major restructuring targeting CAGR 15.44% → 25-30%+) landed in 5 commits on 2026-04-17 afternoon. All toggles at default ON. Immediate next action is a Colab FULL REBUILD (~3h) to measure cumulative CAGR effect. SESSION_HANDOFF.md §2 has the exact cells to paste and the recovery-verdict Cell E. Ship gate: CAGR ≥ 25%.
```

---

## 5. Files that persist across machines

Everything source-of-truth is in git on `origin/master`:

- `r1000_top30_institutional.py` — engine (~27k lines after Phase 8)
- `r1000_data_collector.py` — collector
- `r1000_operator.py` — live operator layer
- `r1000_portfolio_state.py` — state persistence
- `colab_run.ipynb` — runbook (Cell 2 has phase env toggles — Phase 8 toggles rely on defaults, no edits needed)
- `CLAUDE.md` — project brain (short)
- `PHASE_ROADMAP.md` — phase plan (PHASE_8_PROPOSAL.md is the successor for 8a/8b/8c)
- `PHASE_8_PROPOSAL.md` — Phase 8 design & expected CAGR deltas
- `DIAGNOSIS_FACTOR_IC.md` / `DIAGNOSIS_COUNTERFACTUAL.md` / `DIAGNOSIS_BUGS.md` / `DIAGNOSIS_factor_ic.csv` — data evidence
- `CHANGELOG.md` — decision log (every commit has a matching entry)
- `SESSION_HANDOFF.md` — this file; single-item inbox
- `PROPOSAL_defensive_upgrades.md`, `PROPOSAL_growth_regime_offense_defense.md` — older design docs (Phase 4/6 reference)

What's NOT in git (lives only on Google Drive):

- `/content/drive/MyDrive/r1000-quant-engine/` — Cell A keeps this `git reset --hard origin/master` on every run.
- `/content/drive/MyDrive/r1000_top30_institutional/` — data folder with `cache_*/`, `feature_store/`, `checkpoints/`, `outputs/`, `companyfacts.zip`. Cell A `os.chdir()`'s into it.
- Local mirror (Windows): `G:\내 드라이브\r1000_top30_institutional\` — accessible for post-run analysis.

Any machine with (a) a clone of the repo and (b) the Drive mounted has full state.

---

## 6. Quick reference — Phase status + toggles (post-Phase 8)

| Phase | cfg field | env var | Default | A/B status |
|---|---|---|---|---|
| 1 | (auto via `phase_is_enabled`) | `PHASE_PHASE1_ALPHA_ENABLED` | ON | **keepcols fix landed in 8b.3 — now actually measurable on next rebuild** |
| 2 | (no flag) | `PHASE_PHASE2_INDUSTRY_ENABLED` | ON | Industry_rotation_signal zeroed by 8a.1 because IC -0.012 |
| 3 | `sleeve_weight_renorm_enabled` | `PHASE_PHASE3_RENORM_ENABLED` | OFF | REJECTED (ship failure: ΔCAGR -2.30pp) |
| 4 | `regime_dynamic_sleeve_weights_enabled` | `PHASE_PHASE4_REGIME_WEIGHTS_ENABLED` | OFF | A/B pending — revisit after Phase 8 ships |
| 5 | `sub_industry_leader_laggard_enabled` | `PHASE_PHASE5_LEADER_LAGGARD_ENABLED` | **OFF (new default after 8a.2)** | Rejected — factor IC ~0 |
| 6a | `drawdown_breaker_multilevel_enabled` | `PHASE_PHASE6A_BREAKER_ENABLED` | ON | Dormant in 83-month sample — keep |
| 6b | `vix_level_guard_enabled` | `PHASE_PHASE6B_VIX_ENABLED` | ON | Dormant in 83-month sample — keep |
| 6c | `volatility_targeting_enabled` | `PHASE_PHASE6C_VOLTARGET_ENABLED` | OFF | A/B pending |
| 7a | `phase7a_insider_accruals_enabled` | `PHASE_PHASE7A_INSIDER_ACCRUALS_ENABLED` | OFF | A/B pending |
| **8a.1** neg-IC drop | — (hard-coded) | `PHASE_PHASE8A_NEG_IC_DROP` | **ON** | QUICK-measurable |
| **8a.4** hold-persistence | `phase8a_hold_persistence_enabled` | `PHASE_PHASE8A_HOLD_PERSISTENCE` | **ON** | QUICK-measurable |
| **8a.5** macro clamp | — (always active) | — | always | safety fix |
| **8b.1** long-lookback momentum | `phase8b_long_lookback_enabled` | `PHASE_PHASE8B_LONG_LOOKBACK` | **ON** | **FULL rebuild required** |
| **8b.3** Phase 1 keepcols | — (always active) | — | always | structural fix |
| **8c.1** megacap future override | `phase8c_megacap_future_override_enabled` | `PHASE_PHASE8C_MEGACAP_OVERRIDE` | **ON** | QUICK-measurable |
| **8c.2** growth-adj valuation | `phase8c_growth_adj_valuation_enabled` | `PHASE_PHASE8C_GROWTH_ADJ_VALUATION` | **ON** | QUICK-measurable |

**Deferred Phase 8 items** (not yet implemented):
- **Phase 8d**: IC-proportional sleeve reweighting — requires post-FULL measurement + factor correlation audit first
- **Phase 8e**: r_12m ML training target — requires walk-forward train-target refactor (medium risk)

---

## 7. How to rotate this handoff

When:
- **FULL rebuild ships CAGR ≥ 25%**: rewrite §0-§2 to "Phase 8 shipped, Phase 8d planning" and clear §3 decision tree.
- **Regression ≥ 5pp drop**: rewrite §2 to "isolate offender via A/B toggle". §3c becomes §2.
- **Partial ship**: §3b becomes §2 with the specific A/B protocol.

Never accumulate multiple handoff files. This is a single-item inbox, not a log.
