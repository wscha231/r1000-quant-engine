# Session Handoff — 2026-04-17 16:30 KST

> **WHO AM I**: r1000 Quant Engine project (Russell 1000 Top-30 institutional).
> **PURPOSE OF THIS FILE**: shortest possible "pick-up-where-we-left-off" brief for a new Claude / Codex / GPT chat session on a different machine.
> **LIFETIME**: rewrite this file whenever a phase ships or a new blocker appears. One active handoff only.

---

## 0. TL;DR — one-paragraph resume brief

Phase 8 (commits `4cd938e` → `9b083d2`) shipped on 2026-04-17 with **measured CAGR 21.86% / Sharpe 0.99 / MaxDD -32.1%** vs the 1d4fb40 baseline (CAGR 20.10% / Sharpe 1.08 / MaxDD -23.6%). Result: **PARTIAL** ship per `EXECUTION_PLAN.md` (CAGR up +1.76pp, but Sharpe down -0.09 and MaxDD worsened -8.5pp). Critical structural problem identified: **early sleeve collapsed to 0 names selected, future sleeve absorbed 71.6% of portfolio (target 45%), sleeve labels lost archetype meaning (NVDA classified as core_compounder by argmax-of-factor-scores instead of by mega-cap structural rule).** User feedback: "core/future/early can't tell apart" + "$500B 도 10년 후엔 작을 수 있다 — 능동적으로 분리". Phase 9 (commit `ced5db6`) lands two architectural fixes BOTH defaulting ON, BOTH `QUICK_RESCORE`-compatible (~20 min iteration, no FULL rebuild needed):
- **C1**: rebalance Phase 8b multi_year_winner_score sleeve weights (future 0.90→0.50, early 0.60→0.80, core 0.40→0.30) to break future-sleeve dominance
- **C2**: replace argmax+override sleeve assignment with explicit cross-sectional **percentile-based thesis gates** (mega-cap auto-core, scaling-up future, EPS-inflection-or-technical-breakout early, no-thesis dropped). Empirical sim on real 610-name universe gave clean 9.5/8.9/9.0% candidate split per sleeve.

Current HEAD = `ced5db6`. **Next action: Colab QUICK_RESCORE (~20 min) to measure C1+C2 combined effect.** Ship gate: CAGR ≥ 22.5% AND Sharpe ≥ 1.0 AND early sleeve ≥ 4 names selected.

---

## 1. Recent timeline on `origin/master` (newest first)

| Commit | Title | Phase | Requires | Default |
|---|---|---|---|---|
| `ced5db6` | **Phase 9 C1+C2: multi_year rebalance + percentile thesis-gate** | 9.C1 + 9.C2 | QUICK | ON |
| `2c2101c` | EXECUTION_PLAN.md: Drive audit + staged roadmap | docs | — | — |
| `d87160d` | hard_sanitize dedup fix (CRITICAL — unblocked Phase 8 FULL run) | 8 fix | no rebuild | always-on |
| `9b083d2` | Phase 8d: IC-reweight + long-horizon alpha composite | 8d.1 + 8d.2 | QUICK | ON |
| `300affc` | Phase 8 review fixes: weight-0 skip + r_1m lookahead | review | no rebuild | always-on |
| `caddec3` | Phase 8c: Mega-cap future override + growth-adj valuation | 8c.1 + 8c.2 | QUICK | ON |
| `3e44d35` | Phase 8b.1: Long-lookback momentum (mom_18m/24m/36m) | 8b.1 | FULL (already done) | ON |
| `e3bf29d` | Phase 8a.4: Hold persistence bonus | 8a.4 | QUICK | ON |
| `3624e06` | Phase 8a.1+8a.2: Drop neg-IC factors + Phase 5 default OFF | 8a.1/8a.2 | QUICK | ON / OFF |
| `4cd938e` | Phase 8a safety: rolling_robust_z + macro clamp + Phase 1 keepcols | 8a.5 + 8b.3 | FULL (already done) | always-on |
| `027c5b3` | Phase C diagnosis docs (factor IC, counterfactuals, bugs, Phase 8 proposal) | C | — | — |

**Current `ENGINE_REUSE_VERSION`**: `"2026-04-17-phase8b-long-lookback-momentum"`. **NO new FULL rebuild needed** for Phase 9 — feature_store schema unchanged. Phase 9 is post-feature-store sleeve label assignment + cfg weight tweak.

See `EXECUTION_PLAN.md`, `ARCHITECTURE_REVIEW.md` (incl §6b sleeve taxonomy redesign), `DIAGNOSIS_FACTOR_IC.md`, `DIAGNOSIS_COUNTERFACTUAL.md`, `DIAGNOSIS_BUGS.md`, `PHASE_8_PROPOSAL.md`, `REFACTOR_PLAN.md` for design history + future plan.

---

## 2. What the user must do NEXT — **Colab QUICK_RESCORE (~20 min)**

Goal: measure Phase 9 C1+C2 combined effect. NO FULL rebuild needed (feature_store from Phase 8 run is reused).

### Cell A — git sync (paste at top of notebook every session)

```python
import subprocess, sys, os
REPO_DIR = '/content/drive/MyDrive/r1000-quant-engine'
DATA_DIR = '/content/drive/MyDrive/r1000_top30_institutional'
subprocess.run(['git', '-C', REPO_DIR, 'fetch', 'origin', 'master'], check=True)
subprocess.run(['git', '-C', REPO_DIR, 'reset', '--hard', 'origin/master'], check=True)
subprocess.run(['git', '-C', REPO_DIR, 'log', '--oneline', '-5'])
# Expected HEAD: ced5db6 "Phase 9 C1 + C2: multi_year weight rebalance + percentile-based sleeve thesis-gate"
if REPO_DIR not in sys.path:
    sys.path.insert(0, REPO_DIR)
os.chdir(DATA_DIR)
```

### Cell 2 — toggles (★ QUICK_RESCORE not FULL ★)

```python
QUICK_RESCORE_ONLY = True              # ★ QUICK, ~20 min
OPTION_1_FULL_REBUILD = False
FRESH_START = False
NUKE_ALL = False
# All Phase 1-9 toggles default 'auto':
#   Phase 1+2 ON, Phase 3 OFF (rejected), Phase 4 OFF (pending),
#   Phase 5 OFF (rejected), Phase 6a/6b ON, Phase 6c OFF (pending),
#   Phase 7a OFF (pending), Phase 8a/b/c/d ON,
#   Phase 9 C1 ON, Phase 9 C2 ON.
```

### Cell 3 SKIP (collector data already cached from earlier today's run)

### Cell 4 — pipeline (~20 min in QUICK_RESCORE mode)

Run as-is. Look for "QUICK RESCORE MODE" header in output.

### Cell E — verdict snippet (paste as new code cell after Cell 4)

```python
import json, pathlib, pandas as pd
BASE = pathlib.Path('/content/drive/MyDrive/r1000_top30_institutional')

# Phase 9 diagnostic + sleeve distribution
print("=" * 70); print("PHASE 9 DIAGNOSTIC — sleeve distribution + activity flags"); print("=" * 70)
scored = pd.read_csv(BASE / 'outputs/scored_latest.csv', low_memory=False)
print(f"\\nScored rows: {len(scored)}")
sleeve_dist = scored['portfolio_sleeve_label'].value_counts()
print(f"\\nSleeve distribution (raw):"); print(sleeve_dist)

phase9_cols = ['phase9_thesis_gate_active','phase9_c1_rebalance_active',
               'phase9_core_eligible','phase9_future_eligible',
               'phase9_early_eligible','phase9_unassigned',
               'phase9_mktcap_percentile']
print("\\nPhase 9 diagnostic columns:")
for c in phase9_cols:
    if c in scored.columns:
        v = pd.to_numeric(scored[c], errors='coerce').fillna(0)
        print(f"  {c:40s}  mean={v.mean():.3f}  sum={v.sum():.0f}")
    else:
        print(f"  {c:40s}  MISSING")

# Final portfolio
pf = pd.read_csv(BASE / 'outputs/portfolio_latest.csv')
print(f"\\nFinal portfolio: {len(pf)} positions")
print(f"  Sleeve dist: {pf.groupby('portfolio_sleeve_label').size().to_dict()}")
print(f"  Top 10 by weight:")
print(pf.nlargest(10, 'weight')[['ticker','portfolio_sleeve_label','weight']].to_string(index=False))

# Backtest metrics vs baseline
print("\\n" + "=" * 70); print("MAIN PORTFOLIO METRICS vs Phase 8 baseline (d87160d)"); print("=" * 70)
bm = json.loads((BASE / 'outputs/backtest_metrics.json').read_text())
phase8_baseline = {'cagr': 0.2186, 'sharpe': 0.9856, 'max_dd': -0.3208, 'ir': 0.5800,
                   'avg_turnover_monthly': 0.5119, 'avg_stock_names': 21.34}
print(f"  {'metric':24s} {'new':>10s} {'Phase 8':>10s} {'delta':>14s}")
for k in ['cagr','sharpe','max_dd','ir','avg_turnover_monthly','avg_stock_names','beat_month_ratio','excess_cagr']:
    new_v = bm.get(k, float('nan')); bl_v = phase8_baseline.get(k)
    if bl_v is None: print(f"  {k:24s} {new_v:>10.4f}"); continue
    if k in ['cagr','max_dd','avg_turnover_monthly','excess_cagr']:
        d_str = f"{(new_v - bl_v) * 100:+.2f}pp"
    else:
        d_str = f"{new_v - bl_v:+.4f}"
    print(f"  {k:24s} {new_v:>10.4f} {bl_v:>10.4f} {d_str:>14s}")

# Sleeve allocation reality vs target
print("\\n=== SLEEVE ALLOCATION (from weights_latest) ===")
weights = json.loads((BASE / 'outputs/weights_latest.json').read_text())
print(f"  target:  {weights.get('sleeve_target_weights')}")
print(f"  actual:  {weights.get('sleeve_actual_weights')}")
print(f"  counts:  {weights.get('sleeve_selected_counts', '?')}")

print("\\n=== VERDICT ===")
dCAGR = (bm['cagr'] - phase8_baseline['cagr']) * 100
dSharpe = bm['sharpe'] - phase8_baseline['sharpe']
dMaxDD = (bm['max_dd'] - phase8_baseline['max_dd']) * 100
early_count = sum(1 for v in (weights.get('sleeve_selected_counts') or {}).values() if v)
early_n = (weights.get('sleeve_selected_counts') or {}).get('early_scout', 0)
print(f"  ΔCAGR     {dCAGR:+.2f}pp   (gate >= 0.5pp)")
print(f"  ΔSharpe   {dSharpe:+.4f}    (gate >= -0.05)")
print(f"  ΔMaxDD    {dMaxDD:+.2f}pp   (gate >= -3pp; positive better)")
print(f"  early_scout selected: {early_n}    (gate >= 4)")

if dCAGR >= 0.5 and dSharpe >= -0.05 and dMaxDD >= -3.0 and early_n >= 4:
    print("\\n  --> SHIP. Phase 9 C1+C2 default ON wins. Stage 2 (refactor + cleanup) next.")
elif dCAGR >= -2.0 and early_n >= 2:
    print("\\n  --> PARTIAL. Run A/B isolation (each ~20 min):")
    print("      a) PHASE9_C1_REBALANCE='0' QUICK_RESCORE -> C1 isolated effect")
    print("      b) PHASE9_THESIS_GATE='0' QUICK_RESCORE  -> C2 isolated effect")
else:
    print("\\n  --> REGRESS. Roll back Phase 9 (set both Phase 9 toggles to '0' as default).")
```

**Paste the full Cell E output back to the chat when Cell 4 finishes.** Verdict line drives the next action.

---

## 3. Decision tree after QUICK_RESCORE

### 3a. SHIP (CAGR ≥ +0.5pp, Sharpe -0.05+, MaxDD -3pp+, early ≥ 4 names)

1. Update CHANGELOG with measured Phase 9 metrics as new baseline.
2. Proceed to **Phase 9 C3**: add EPS turn-positive flags (profit_turn_positive_4q, etc.) to early eligibility gate. Requires fund_panel modification + FULL rebuild.
3. After C3: start **Refactor Phase A** (5-module split per `REFACTOR_PLAN.md`) on the now-stable Phase 9 baseline.

### 3b. PARTIAL (CAGR -2pp to +0.5pp OR mixed metrics)

Run two QUICK_RESCORE A/B isolation passes (each ~20 min, total 40 min):

```python
# Run A: C1 isolated (C2 OFF)
PHASE9_C1_REBALANCE = 'auto'
PHASE9_THESIS_GATE = '0'

# Run B: C2 isolated (C1 OFF)
PHASE9_C1_REBALANCE = '0'
PHASE9_THESIS_GATE = 'auto'
```

Compare each isolated effect to Phase 8 baseline. Ship whichever (or both) gives net positive metrics.

### 3c. REGRESS (CAGR < -2pp OR early < 2 names)

1. Set both Phase 9 toggles to '0' as cfg defaults (`phase9_c1_rebalance_enabled = False`, `phase9_thesis_gate_enabled = False`).
2. Phase 9 stays in code as `experimental` for future re-evaluation but is OFF by default.
3. Investigate: is the percentile threshold off? Are EPS turn-positive flags needed before Phase 9 can ship?
4. Fall back to Phase 8 baseline (CAGR 21.86%) as the production baseline.

---

## 4. Bootstrap prompt for a fresh chat session

```
I'm continuing work on the r1000 Quant Engine project. Before doing anything else, please:

1. Read `CLAUDE.md` — project basics.
2. Read `SESSION_HANDOFF.md` — current pending work (THIS is the most important file for picking up where we left off).
3. Read the last ~400 lines of `CHANGELOG.md` — most recent decisions.
4. Read `EXECUTION_PLAN.md` + `ARCHITECTURE_REVIEW.md` — staged roadmap and ceiling assessment.
5. Read `PHASE_8_PROPOSAL.md` and `REFACTOR_PLAN.md` for design history.
6. Read `DIAGNOSIS_FACTOR_IC.md`, `DIAGNOSIS_COUNTERFACTUAL.md`, `DIAGNOSIS_BUGS.md` — data evidence.
7. Check `git log --oneline -10` to confirm latest commit is at or after `ced5db6 "Phase 9 C1 + C2 ..."`.

Only after reading those files, ask me what I want to do next. Do NOT start editing anything until you've read them.

Context: Phase 8 (CAGR 21.86%) shipped PARTIAL; Phase 9 C1+C2 (sleeve thesis-gate redesign) just landed and is awaiting Colab QUICK_RESCORE measurement. SESSION_HANDOFF.md §2 has the exact cells to paste and the verdict snippet.
```

---

## 5. Files that persist across machines

Source-of-truth in git on `origin/master`:

- `r1000_top30_institutional.py` — engine (~27.4k lines after Phase 9)
- `r1000_data_collector.py` — collector
- `r1000_operator.py` — live operator layer
- `r1000_portfolio_state.py` — state persistence
- `colab_run.ipynb` — runbook (Cell 2 has all 18 phase env toggles incl Phase 9)
- `CLAUDE.md` — project brain (short)
- `PHASE_ROADMAP.md` — Phase 1-6 multi-session plan (older, partial coverage)
- `PHASE_8_PROPOSAL.md` — Phase 8 design
- `REFACTOR_PLAN.md` — module split + observability infrastructure plan
- `ARCHITECTURE_REVIEW.md` — cold first-principles assessment + Phase 9 + sleeve redesign rationale
- `EXECUTION_PLAN.md` — 4-stage roadmap (Stage 0 = current Phase 9, Stage 2 = refactor + cleanup, Stage 3 = optional structural)
- `DIAGNOSIS_FACTOR_IC.md` / `DIAGNOSIS_COUNTERFACTUAL.md` / `DIAGNOSIS_BUGS.md` / `DIAGNOSIS_factor_ic.csv` — Phase C empirical evidence
- `CHANGELOG.md` — decision log (every commit has a matching entry)
- `SESSION_HANDOFF.md` — this file
- `PROPOSAL_defensive_upgrades.md` / `PROPOSAL_growth_regime_offense_defense.md` — older design refs

Drive (NOT in git):
- `/content/drive/MyDrive/r1000-quant-engine/` — Cell A keeps `git reset --hard origin/master` on every run.
- `/content/drive/MyDrive/r1000_top30_institutional/` — data folder (`cache_*/`, `feature_store/`, `checkpoints/`, `outputs/`, `companyfacts.zip`).
- Local Windows mirror: `G:\내 드라이브\r1000_top30_institutional\`.

---

## 6. Quick reference — Phase status + toggles (post Phase 9)

| Phase | cfg field | env var | Default | A/B status |
|---|---|---|---|---|
| 1 (alpha) | (auto via phase_is_enabled) | `PHASE_PHASE1_ALPHA_ENABLED` | ON | Shipped |
| 2 (industry RS) | (no flag) | `PHASE_PHASE2_INDUSTRY_ENABLED` | ON | Shipped (signal in C2 thesis gate too) |
| 3 (sleeve renorm) | `sleeve_weight_renorm_enabled` | `PHASE_PHASE3_RENORM_ENABLED` | OFF | REJECTED (-2.30pp CAGR) |
| 4 (regime mult) | `regime_dynamic_sleeve_weights_enabled` | `PHASE_PHASE4_REGIME_WEIGHTS_ENABLED` | OFF | A/B pending |
| 5 (sub-industry) | `sub_industry_leader_laggard_enabled` | `PHASE_PHASE5_LEADER_LAGGARD_ENABLED` | OFF | REJECTED (IC ~0) |
| 6a (DD breaker) | `drawdown_breaker_multilevel_enabled` | `PHASE_PHASE6A_BREAKER_ENABLED` | ON | Dormant in 83-month sample |
| 6b (VIX guard) | `vix_level_guard_enabled` | `PHASE_PHASE6B_VIX_ENABLED` | ON | Dormant in 83-month sample |
| 6c (vol target) | `volatility_targeting_enabled` | `PHASE_PHASE6C_VOLTARGET_ENABLED` | OFF | A/B pending |
| 7a (insider+accruals) | `phase7a_insider_accruals_enabled` | `PHASE_PHASE7A_INSIDER_ACCRUALS_ENABLED` | OFF | A/B pending |
| **8a.1** neg-IC drop | (hard-coded) | `PHASE_PHASE8A_NEG_IC_DROP_ENABLED` | ON | Shipped (Phase 8 PARTIAL) |
| **8a.4** hold-persist | `phase8a_hold_persistence_enabled` | `PHASE_PHASE8A_HOLD_PERSISTENCE_ENABLED` | ON | Shipped |
| **8a.5** macro clamp | (always active) | — | always | Shipped (safety) |
| **8b.1** long-lookback | `phase8b_long_lookback_enabled` | `PHASE_PHASE8B_LONG_LOOKBACK_ENABLED` | ON | Shipped |
| **8b.3** Phase 1 keepcols | (always active) | — | always | Shipped (structural) |
| **8c.1** megacap override | `phase8c_megacap_future_override_enabled` | `PHASE_PHASE8C_MEGACAP_OVERRIDE_ENABLED` | ON | Shipped (also gated by Phase 9 C2) |
| **8c.2** growth-adj val | `phase8c_growth_adj_valuation_enabled` | `PHASE_PHASE8C_GROWTH_ADJ_VALUATION_ENABLED` | ON | Shipped |
| **8d.1** IC reweight | `phase8d_ic_reweight_enabled` | `PHASE_PHASE8D_IC_REWEIGHT_ENABLED` | ON | Shipped |
| **8d.2** long-horizon alpha | `phase8d_long_horizon_alpha_enabled` | `PHASE_PHASE8D_LONG_HORIZON_ALPHA_ENABLED` | ON | Shipped |
| **9.C1** multi_year weight rebalance | `phase9_c1_rebalance_enabled` | `PHASE_PHASE9_C1_REBALANCE_ENABLED` | ON | **A/B pending (this run)** |
| **9.C2** percentile thesis gate | `phase9_thesis_gate_enabled` | `PHASE_PHASE9_THESIS_GATE_ENABLED` | ON | **A/B pending (this run)** |

**Deferred work** (per `EXECUTION_PLAN.md` Stage 2-3):

- **Phase 9 C3**: EPS turn-positive flags (profit_turn_positive_4q etc.). Requires fund_panel modification + FULL rebuild. ~2-3h.
- **Refactor Phase A**: 5-module split (`r1000_config.py / r1000_helpers.py / r1000_features.py / r1000_signals.py / r1000_pipeline.py`) + facade + observability + tests. ~12-16h focused work.
- **Phase 9 Subtractive**: delete dead phases (3 / 5 / 7a if A/B-rejected) + 153 noise factors + cluster consolidation. ~8h. Saves 7-10k lines.
- **Phase 8e proper**: r_12m ML training target. Walk-forward refactor required. Best done on modular code post-Refactor. ~11-13h.
- **Optional structural** (Stage 3): one of {quarterly rebalance / top-10 concentration / R2000 universe expansion}. Each ~1 day to ~1 week.

---

## 7. How to rotate this handoff

When:
- **Phase 9 C1+C2 ships** → §0/§1/§2 become "Phase 9 baseline established, next is Phase 9 C3 EPS turn-positive flags".
- **Phase 9 PARTIAL** → §2 becomes "A/B isolation protocol from §3b" and rerun.
- **Phase 9 REGRESS** → §0 becomes "Phase 9 rolled back; Phase 8 (CAGR 21.86%) is production baseline; refactor next".

Never accumulate multiple handoff files. Single-item inbox only.
