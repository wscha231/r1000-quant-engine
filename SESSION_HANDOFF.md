# Session Handoff — 2026-04-18 12:30 KST

> **WHO AM I**: r1000 Quant Engine project (Russell 1000 Top-30 institutional).
> **PURPOSE OF THIS FILE**: shortest possible "pick-up-where-we-left-off" brief for a new Claude / Codex / GPT chat session on a different machine.
> **LIFETIME**: rewrite this file whenever a phase ships or a new blocker appears. One active handoff only.

---

## 0. TL;DR — one-paragraph resume brief

**Phase 9 C1+C2 SHIPPED** 2026-04-18. User accepted PARTIAL verdict (ΔCAGR -0.74pp vs Phase 8) in exchange for dramatic risk-adjusted and structural improvements: Sharpe +0.08, MaxDD -5.78pp, sleeve taxonomy restored (early_scout 0 → 8 names), mega-cap core rule working as designed (NVDA/GOOG in core_compounder via percentile gate). Phase 9 C1+C2 is the NEW PRODUCTION BASELINE. Rotated baseline snapshot:

| metric | value | source |
|---|---|---|
| CAGR | **21.12%** | `run_local.py --verdict-only` against Drive outputs (commit `33581bc` FULL REBUILD) |
| Sharpe | **1.0664** | |
| MaxDD | **-26.30%** | |
| IR | **0.6977** | |
| excess_cagr | **+7.63%** vs S&P 500 | |
| avg_stock_names | **24.35** | |
| beat_month_ratio | **61.45%** | |
| sleeve_counts | core 4 / future 5 / early 8 | NVDA GOOG JNJ VRT ∥ GEV FTI LITE CIEN MRVL ∥ ETR + 7 |

**Next step: Phase 9 C3 implementation** per `PHASE_9_C3_PROPOSAL.md`. Hypothesis: EPS turn-positive flags (`profit_turn_positive_4q` / `cashflow_turn_positive_4q` / `roe_turn_positive_4q`) + "still-loss-improving" branch tightens early_scout quality, which may recover some of the -0.74pp CAGR. Requires ENGINE_REUSE_VERSION bump → FULL rebuild (~3-4h local CPU / ~2-3h Colab). Design complete; implementation is ~40 LOC + keep_cols whitelist + 2 cfg fields + Cell 2 toggle. After C3 SHIP verdict: Refactor Phase A (REFACTOR_PLAN.md §6).

**Ship gate for C3 (or any next change)**: ΔCAGR ≥ +0.5pp AND ΔSharpe ≥ -0.05 AND ΔMaxDD ≥ -3pp vs current baseline (Phase 9 C1+C2, see CURRENT_BASELINE in `run_local.py`).

Current HEAD = `79d6fe8` (local runner + verdict). Next commit: baseline rotation paperwork. Commit after that: C3 implementation.

---

## 1. Recent timeline on `origin/master` (newest first)

| Commit | Title | Phase | Requires | Default |
|---|---|---|---|---|
| `527fdde` | **Phase 9 C3 design + refactor plan update** (docs only) | 9.C3 design | — | — |
| `afaa768` | Run banner: print git commit SHA for run provenance | ops | no rebuild | always-on |
| `33581bc` | Phase 9 docs + notebook: CHANGELOG, SESSION_HANDOFF, Cell 2 toggles | 9 docs | — | — |
| `ced5db6` | **Phase 9 C1+C2: multi_year rebalance + percentile thesis-gate** | 9.C1 + 9.C2 | QUICK | ON |
| `2c2101c` | EXECUTION_PLAN.md: Drive audit + staged roadmap | docs | — | — |
| `d87160d` | hard_sanitize dedup fix (CRITICAL — unblocked Phase 8 FULL run) | 8 fix | no rebuild | always-on |
| `9b083d2` | Phase 8d: IC-reweight + long-horizon alpha composite | 8d.1 + 8d.2 | QUICK | ON |
| `caddec3` | Phase 8c: Mega-cap future override + growth-adj valuation | 8c.1 + 8c.2 | QUICK | ON |
| `3e44d35` | Phase 8b.1: Long-lookback momentum (mom_18m/24m/36m) | 8b.1 | FULL (already done) | ON |
| `4cd938e` | Phase 8a safety: rolling_robust_z + macro clamp + Phase 1 keepcols | 8a.5 + 8b.3 | FULL (already done) | always-on |

**Current `ENGINE_REUSE_VERSION`**: `"2026-04-17-phase8b-long-lookback-momentum"`. **Phase 9 C1+C2 are post-feature-store changes — no version bump.** The in-progress FULL REBUILD was overkill for measuring C1+C2 (a QUICK_RESCORE would have worked in ~20 min), but since it ran, the outputs are valid for verdict.

See `EXECUTION_PLAN.md`, `ARCHITECTURE_REVIEW.md` (incl §6b sleeve taxonomy redesign), `PHASE_9_C3_PROPOSAL.md`, `REFACTOR_PLAN.md` §12 (5-stage sequencing) for design history + forward plan.

---

## 2. Next step — Phase 9 C3 implementation

Phase 9 C1+C2 is shipped. C3 adds EPS turn-positive flags to sharpen the early_scout gate. Detailed design in `PHASE_9_C3_PROPOSAL.md`. Implementation flow:

### Step 1 — smoke test current state
```bash
py -3 tests/smoke_test.py
# expect 18/18 passed
```

### Step 2 — add C3 code per PHASE_9_C3_PROPOSAL.md §3

Touch surface (all in the SAME commit, bundled C3 feature code; keep refactor separate):

| File | Change |
|---|---|
| `r1000_top30_institutional.py` | • `PHASE9_C3_TURNAROUND_COLUMNS` constant (~line 1080)<br>• Add `d["roe_sign_flip_pos"] = _sign_flip_pos("roe_proxy")` after line 12228<br>• Add 4 alias columns (profit_turn_positive_4q, cashflow_turn_positive_4q, roe_turn_positive_4q, any_profitability_turn_positive_4q) after the `any_profit_sign_flip_pos` block<br>• Extend `carry_cols` list (line ~12358) with 5 new names<br>• Add `+ PHASE9_C3_TURNAROUND_COLUMNS` to `build_feature_store.keep_cols` (line 14327) AND to `hard_sanitize` call (line 14354)<br>• Extend Phase 9 C2 early-scout gate block (line ~19357) with `_p9_eps_turn_positive` + `_p9_still_loss_but_improving` branches<br>• Add 2 cfg fields: `phase9_c3_turnaround_enabled: bool = True`, `phase9_c3_loss_narrowing_threshold: float = 0.3`<br>• Bump `ENGINE_REUSE_VERSION` → `"2026-04-18-phase9c3-turnaround-flags"` |
| `colab_run.ipynb` Cell 2 | `PHASE9_C3_TURNAROUND = 'auto'` + env binding + print-loop entry |
| `run_local.py` | Add `--phase9-c3` CLI flag mirroring Phase 9 C1/C2 toggles |
| `tests/smoke_test.py` | Add 3 tests: `import.phase9_c3_constants_exported`, `regression.phase9_c3_columns_complete`, `structural.phase9_c3_carry_cols_present` |
| `CHANGELOG.md` | Agent Update Contract entry |

### Step 3 — pre-push validation
```bash
py -3 tests/smoke_test.py
# expect 21/21 passed (18 existing + 3 new)
```

### Step 4 — FULL REBUILD (required: feature_store schema change)
```bash
py -3 run_local.py --full          # ~3-4h local CPU
# or
# Colab Cell A + Cell 4 if GPU needed (~2-3h)
```

### Step 5 — Cell E verdict
```bash
py -3 run_local.py --verdict-only
```

Ship gate: ΔCAGR ≥ +0.5pp AND ΔSharpe ≥ -0.05 AND ΔMaxDD ≥ -3pp vs Phase 9 C1+C2 baseline (defined in `run_local.py CURRENT_BASELINE`).

### Ship vs Partial vs Regress decision tree (same as C1+C2)
- **SHIP** → rotate CURRENT_BASELINE in run_local.py + SESSION_HANDOFF §0 to Phase 9 C1+C2+C3 metrics. Proceed to Refactor Phase A (REFACTOR_PLAN.md §6).
- **PARTIAL** → user decision: A/B isolate C3 ON/OFF, or accept taxonomy improvement with marginal CAGR trade (same call we just made for C1+C2).
- **REGRESS** → revert the C3 commit; Phase 9 C1+C2 remains baseline; re-plan.

---

## 2b. Legacy commands — local or Colab runs on current baseline

### If you want to re-verify current baseline (~2s, no pipeline)
```bash
py -3 run_local.py --verdict-only
# expect ΔCAGR +0.00pp vs Phase 9 C1+C2 baseline (comparing itself to itself)
```

### If you want full local run (~15-25 min QUICK / ~3-4h FULL)
```bash
py -3 run_local.py                 # QUICK_RESCORE (cached feature_store + models)
py -3 run_local.py --full          # FULL rebuild (required after FS schema change)
py -3 run_local.py --phase9-c1=0   # A/B: C1 OFF
py -3 run_local.py --phase9-c2=0   # A/B: C2 OFF
```

### If you prefer Colab (legacy, documented below)

### Step 1 -- verify run completed

```python
import pathlib, time
BASE = pathlib.Path('/content/drive/MyDrive/r1000_top30_institutional')
for f in ['outputs/scored_latest.csv', 'outputs/backtest_metrics.json',
          'outputs/weights_latest.json', 'outputs/portfolio_latest.csv',
          'outputs/top30_latest.csv']:
    p = BASE / f
    if p.exists():
        mtime = time.strftime('%Y-%m-%d %H:%M KST', time.localtime(p.stat().st_mtime))
        print(f'  OK   {f:40s}  mtime={mtime}')
    else:
        print(f'  MISS {f:40s}')
```

If any files missing or mtime older than 2026-04-17 08:10 KST: the FULL REBUILD crashed or was interrupted. In that case:
1. Ask user for crash traceback / Colab scrollback.
2. If unrecoverable, switch to QUICK_RESCORE (~20 min) from current HEAD `527fdde` which includes commit banner SHA.

If all files present with recent mtime: proceed to Step 2.

### Step 2 — Cell E verdict snippet

```python
import json, pathlib, pandas as pd
BASE = pathlib.Path('/content/drive/MyDrive/r1000_top30_institutional')

print("=" * 70); print("PHASE 9 C1+C2 DIAGNOSTIC"); print("=" * 70)

scored = pd.read_csv(BASE / 'outputs/scored_latest.csv', low_memory=False)
print(f"\nScored rows: {len(scored)}")
sleeve_dist = scored['portfolio_sleeve_label'].value_counts()
print(f"\nSleeve distribution (raw):"); print(sleeve_dist)

phase9_cols = ['phase9_thesis_gate_active',
               'phase9_core_eligible','phase9_future_eligible',
               'phase9_early_eligible','phase9_unassigned',
               'phase9_mktcap_percentile']
print("\nPhase 9 diagnostic columns (expect all present if C2 active):")
for c in phase9_cols:
    if c in scored.columns:
        v = pd.to_numeric(scored[c], errors='coerce').fillna(0)
        print(f"  {c:40s}  mean={v.mean():.3f}  sum={v.sum():.0f}")
    else:
        print(f"  {c:40s}  MISSING (C2 toggle may be off)")

pf = pd.read_csv(BASE / 'outputs/portfolio_latest.csv')
print(f"\nFinal portfolio: {len(pf)} positions")
print(f"  Sleeve dist: {pf.groupby('portfolio_sleeve_label').size().to_dict()}")
print(f"  Top 10 by weight:")
print(pf.nlargest(10, 'weight')[['ticker','portfolio_sleeve_label','weight']].to_string(index=False))

print("\n" + "=" * 70); print("METRICS vs Phase 8 baseline"); print("=" * 70)
bm = json.loads((BASE / 'outputs/backtest_metrics.json').read_text())
phase8_baseline = {'cagr': 0.2186, 'sharpe': 0.9856, 'max_dd': -0.3208, 'ir': 0.5800,
                   'avg_turnover_monthly': 0.5119, 'avg_stock_names': 21.34}
print(f"  {'metric':24s} {'new':>10s} {'Phase 8':>10s} {'delta':>14s}")
for k in ['cagr','sharpe','max_dd','ir','avg_turnover_monthly','avg_stock_names',
          'beat_month_ratio','excess_cagr']:
    new_v = bm.get(k, float('nan')); bl_v = phase8_baseline.get(k)
    if bl_v is None: print(f"  {k:24s} {new_v:>10.4f}"); continue
    if k in ['cagr','max_dd','avg_turnover_monthly','excess_cagr']:
        d_str = f"{(new_v - bl_v) * 100:+.2f}pp"
    else:
        d_str = f"{new_v - bl_v:+.4f}"
    print(f"  {k:24s} {new_v:>10.4f} {bl_v:>10.4f} {d_str:>14s}")

print("\n=== SLEEVE ALLOCATION ===")
weights = json.loads((BASE / 'outputs/weights_latest.json').read_text())
print(f"  target:  {weights.get('sleeve_target_weights')}")
print(f"  actual:  {weights.get('sleeve_actual_weights')}")
print(f"  counts:  {weights.get('sleeve_selected_counts', '?')}")

print("\n=== VERDICT ===")
dCAGR = (bm['cagr'] - phase8_baseline['cagr']) * 100
dSharpe = bm['sharpe'] - phase8_baseline['sharpe']
dMaxDD = (bm['max_dd'] - phase8_baseline['max_dd']) * 100
early_n = (weights.get('sleeve_selected_counts') or {}).get('early_scout', 0)
print(f"  ΔCAGR     {dCAGR:+.2f}pp   (gate >= +0.5pp)")
print(f"  ΔSharpe   {dSharpe:+.4f}    (gate >= -0.05)")
print(f"  ΔMaxDD    {dMaxDD:+.2f}pp   (gate >= -3pp; positive better)")
print(f"  early_scout selected: {early_n}    (gate >= 4)")

if dCAGR >= 0.5 and dSharpe >= -0.05 and dMaxDD >= -3.0 and early_n >= 4:
    print("\n  --> SHIP. Phase 9 C1+C2 wins. Next: §3a.")
elif dCAGR >= -2.0 and early_n >= 2:
    print("\n  --> PARTIAL. Next: §3b (A/B isolation).")
else:
    print("\n  --> REGRESS. Next: §3c (rollback).")
```

**Paste the full Cell E output (verdict line + metrics table) back to chat.**

---

## 3. Decision tree after Cell E verdict

### 3a. SHIP (CAGR ≥ +0.5pp, Sharpe ≥ -0.05, MaxDD ≥ -3pp, early ≥ 4 names)

**Both Phase 9 C3 AND Refactor Phase A ship** — they are serialized, NOT mutually exclusive. The only choice is the ORDER. Per REFACTOR_PLAN.md §12: Stage 2 picks the first, Stage 3 does the complement.

**Hard rule**: never bundle C3 + Refactor in the same commit. Bisection dies. Ship C3 as its own commit, Refactor as its own commit (actually multiple commits per §6 checklist), each with its own verification.

**Recommended order: C3 first, then Refactor** (~2 days total wall-clock)

Reasons:
- **Fast measurable result**: C3 behavior change measurable within ~3.5h vs 1.5 days.
- **Final FS schema locks in before refactor moves code**: Refactor's byte-exact verification needs a stable feature_store schema as reference. If C3 ships after refactor, the schema changes twice.
- **C3 regression is cheap to revert**: 1-commit revert, refactor continues on Phase 9 C1+C2 baseline. Opposite order means if C3 regresses, refactor is already done on the wrong baseline.
- **Sleeve taxonomy stabilizes first**: user's definition of early sleeve ("eps 적자거나 양전환 막 하거나") is codified before structural refactor cements it.

**Alternative order: Refactor first, then C3** — valid if user prefers long mechanical work before feature work. Pros: C3 becomes single-file change in `r1000_signals.py` post-refactor. Cons: 1.5 days before C3's effect is measurable; refactor's byte-exact reference is Phase 9 C1+C2 (i.e. sleeve count/composition may shift again when C3 lands post-refactor, forcing a second byte-exact verification pass).

#### Before any code change — run smoke test first (~7s local, saves hours)

```bash
py -3 tests/smoke_test.py
```

Runs 17 tests (syntax + structural + import + logic + regression). Target: all pass before `git push` → Colab. Catches ~80% of bugs without burning Colab time. If you add new engine code, add a matching `@_test` entry at the bottom of `tests/smoke_test.py` in the same commit (see file docstring for the template).

#### Step 1 -- Phase 9 C3 (recommended first, ~3.5h wall-clock)

1. **Run smoke test first**: `py -3 tests/smoke_test.py` — must show `17/17 passed` before editing.
2. Implement per `PHASE_9_C3_PROPOSAL.md` §3. Touch surface:
   - `r1000_top30_institutional.py` — new `PHASE9_C3_TURNAROUND_COLUMNS` constant (~line 1080), 5 new fund_panel columns after line 12228, keep_cols + hard_sanitize whitelist (line 14327, 14354), Phase 9 C2 gate extension (line 19357), 2 new cfg fields, ENGINE_REUSE_VERSION bump to `2026-04-17-phase9c3-turnaround-flags`.
   - `colab_run.ipynb` Cell 2 — add `PHASE9_C3_TURNAROUND = 'auto'` toggle + env binding + print-loop entry.
   - `tests/smoke_test.py` — add 2-3 new `@_test` entries: PHASE9_C3_TURNAROUND_COLUMNS constant present, cfg field `phase9_c3_turnaround_enabled` in EngineConfig, early-scout gate respects new branch.
   - `CHANGELOG.md` — Agent Update Contract entry.
3. **Re-run smoke test**: `py -3 tests/smoke_test.py` — expect 20/20 passed (added 3 new tests).
4. Commit + push from fresh checkout.
5. Trigger Colab FULL REBUILD (required — FS schema changes). The `[commit=<sha>]` banner will self-identify the run.
6. Cell E verdict vs Phase 9 C1+C2 baseline (ship gate: ΔCAGR ≥ 0, early count widening, no Sharpe regression > -0.05).
7. If C3 SHIPs: continue to Step 2 (Refactor).
8. If C3 REGRESSes: revert C3 commit, proceed to Step 2 on Phase 9 C1+C2 baseline.

#### Step 2 — Refactor Phase A (~1-1.5 day)

1. Execute `REFACTOR_PLAN.md` §6 checklist (5-module split + §11 observability scaffolding).
2. Byte-exact verification via QUICK_RESCORE diff: pre-refactor `scored_latest.csv` SHA256 must match post-refactor.
3. Commit + push (multiple commits per §6 migration order: config → helpers → features → signals → pipeline → facade).
4. If byte-exact fails: bisect which module move broke which symbol; fix; retest.
5. Post-refactor: update CLAUDE.md "Key Files", PHASE_ROADMAP.md deprecation note, SESSION_HANDOFF.md §5 file list to reflect new module map.

#### After both ship: Stage 4 (Subtractive pass)

Per REFACTOR_PLAN.md §12 Stage 4: delete Phase 3 / Phase 5 / Phase 7a dead branches + 153 zero-IC noise factors. Post-refactor this is mechanical (remove constant + call site in the owning module). ~4-8h. Saves ~15-20% LOC.

### 3b. PARTIAL (CAGR -2pp to +0.5pp OR mixed metrics)

Run two QUICK_RESCORE A/B isolation passes (each ~20 min, total 40 min):

```python
# Run A: C1 isolated (C2 off)
PHASE9_C1_REBALANCE = 'auto'
PHASE9_THESIS_GATE = '0'
# rerun Cell 4 QUICK_RESCORE + Cell E

# Run B: C2 isolated (C1 off)
PHASE9_C1_REBALANCE = '0'
PHASE9_THESIS_GATE = 'auto'
# rerun Cell 4 QUICK_RESCORE + Cell E
```

Compare each isolated effect vs Phase 8 baseline. Ship whichever (or both) gives net positive metrics; roll back the other by editing `EngineConfig` default.

### 3c. REGRESS (CAGR < -2pp OR early < 2 names)

1. Edit `EngineConfig`: `phase9_c1_rebalance_enabled: bool = False` AND `phase9_thesis_gate_enabled: bool = False`.
2. Phase 9 stays in code as `experimental` for future re-evaluation but is OFF by default.
3. Commit + push with message "Roll back Phase 9 C1+C2 defaults after FULL-REBUILD regression".
4. Phase 8 (CAGR 21.86%) becomes production baseline.
5. Re-plan: is the percentile threshold off? Do EPS turn-positive flags (Phase 9 C3) need to ship first to rescue C2?

---

## 4. Bootstrap prompt for a fresh chat session

```
I'm continuing work on the r1000 Quant Engine project. Before doing anything else, please:

1. Read `CLAUDE.md` — project basics.
2. Read `SESSION_HANDOFF.md` — THIS file, the single-item inbox for current pending work.
3. Read the last ~500 lines of `CHANGELOG.md` — most recent decisions (entries since 2026-04-17 Phase 9).
4. Read `EXECUTION_PLAN.md`, `ARCHITECTURE_REVIEW.md`, `REFACTOR_PLAN.md` §12 — staged roadmap.
5. Read `PHASE_9_C3_PROPOSAL.md` if Cell E verdict is SHIP and we're picking Path A.
6. Check `git log --oneline -10` to confirm latest commit is at or after `527fdde` "Phase 9 C3 design + refactor plan update".

Only after reading those files, tell me the Cell E verdict OR ask me for the paste. Do NOT start editing anything until the verdict is known.

Context: Phase 9 C1+C2 (sleeve thesis-gate redesign + multi_year weight rebalance) shipped in code on 2026-04-17. A FULL REBUILD from commit `33581bc` was launched at 08:10 KST 2026-04-17 and should have completed by now. The next action is to verify run completed + run Cell E verdict snippet from SESSION_HANDOFF.md §2, then follow §3 decision tree.
```

---

## 5. Files that persist across machines

Source-of-truth in git on `origin/master`:

- `r1000_top30_institutional.py` — engine (~27.4k lines after Phase 9)
- `r1000_data_collector.py` — collector
- `r1000_operator.py` — live operator layer
- `r1000_portfolio_state.py` — state persistence
- `colab_run.ipynb` — runbook (Cell 2 has all 18 phase env toggles incl Phase 9 C1/C2)
- `CLAUDE.md` — project brain (short)
- **`SESSION_HANDOFF.md` — this file (single-item inbox)**
- `CHANGELOG.md` — decision log (every commit has a matching Agent Update Contract entry)
- `EXECUTION_PLAN.md` — 4-stage roadmap
- `ARCHITECTURE_REVIEW.md` — cold first-principles assessment + sleeve redesign rationale
- `REFACTOR_PLAN.md` — 5-module split + observability + §12 5-stage sequencing diagram
- **`PHASE_9_C3_PROPOSAL.md` — NEW. Phase 9 C3 EPS turn-positive flag design. Read BEFORE implementing C3 (detailed snippets, cfg fields, FS whitelist instructions).**
- `PHASE_8_PROPOSAL.md` — older, Phase 8 design history
- `DIAGNOSIS_FACTOR_IC.md` / `DIAGNOSIS_COUNTERFACTUAL.md` / `DIAGNOSIS_BUGS.md` — Phase C empirical evidence
- `PHASE_ROADMAP.md` — DEPRECATED (only covers Phase 1-6). Use REFACTOR_PLAN.md §12 for current roadmap.
- `PROPOSAL_defensive_upgrades.md` / `PROPOSAL_growth_regime_offense_defense.md` — older design refs

Drive (NOT in git):
- `/content/drive/MyDrive/r1000-quant-engine/` — Cell A keeps `git reset --hard origin/master` on every run.
- `/content/drive/MyDrive/r1000_top30_institutional/` — data folder (`cache_*/`, `feature_store/`, `checkpoints/`, `outputs/`, `companyfacts.zip`).
- Local Windows mirror: `G:\내 드라이브\r1000_top30_institutional\`.

---

## 6. Quick reference — Phase status + toggles (post Phase 9 C1+C2)

| Phase | cfg field | env var | Default | Status |
|---|---|---|---|---|
| 1 (alpha) | (auto via phase_is_enabled) | `PHASE_PHASE1_ALPHA_ENABLED` | ON | Shipped |
| 2 (industry RS) | (no flag) | `PHASE_PHASE2_INDUSTRY_ENABLED` | ON | Shipped (feeds C2 thesis gate) |
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
| **9.C1** multi_year weight rebalance | `phase9_c1_rebalance_enabled` | `PHASE_PHASE9_C1_REBALANCE_ENABLED` | ON | **SHIPPED 2026-04-18** (PARTIAL verdict, user accepted trade-off) |
| **9.C2** percentile thesis gate | `phase9_thesis_gate_enabled` | `PHASE_PHASE9_THESIS_GATE_ENABLED` | ON | **SHIPPED 2026-04-18** (same trade-off; restored sleeve taxonomy) |
| **9.C3** EPS turn-positive flags | `phase9_c3_turnaround_enabled` (proposed) | `PHASE_PHASE9_C3_TURNAROUND_ENABLED` (proposed) | — | **DESIGNED, ready to implement** (`PHASE_9_C3_PROPOSAL.md`; next session's work) |

**Deferred work** (per `REFACTOR_PLAN.md` §12 5-stage sequencing):

- **Stage 2 Option A — Phase 9 C3**: EPS turn-positive flags. Design in `PHASE_9_C3_PROPOSAL.md`. Requires fund_panel modification + FULL rebuild. ~3.5h.
- **Stage 2 Option B — Refactor Phase A**: 5-module split (`r1000_config.py / r1000_helpers.py / r1000_features.py / r1000_signals.py / r1000_pipeline.py`) + facade + observability + tests. ~12-16h focused work.
- **Stage 3 — complement**: whichever of C3 or Refactor wasn't done in Stage 2.
- **Stage 4 — Subtractive**: delete Phase 3 / 5 / 7a dead branches + 153 noise factors. ~4-8h. Saves ~15-20% LOC.
- **Stage 5 — Phase 8e**: r_12m ML training target. Walk-forward refactor required. Best done on modular code post-Refactor. ~11-13h.
- **Optional (separate track)**: one of {quarterly rebalance / top-10 concentration / R2000 universe expansion}. Each ~1 day to ~1 week.

---

## 7. How to rotate this handoff

When:
- **Cell E verdict is SHIP** → §0/§1/§2 become "Phase 9 C1+C2 baseline established, next is Stage 2 (C3 or Refactor per user choice)".
- **Cell E verdict is PARTIAL** → §2 becomes "run A/B isolation per §3b, paste two verdicts".
- **Cell E verdict is REGRESS** → §0 becomes "Phase 9 rolled back; Phase 8 (CAGR 21.86%) is production baseline; next is Refactor first, then re-plan Phase 9".
- **Phase 9 C3 ships** (after Stage 2 Option A) → §0 becomes "Phase 9 C1+C2+C3 baseline established, next is Refactor".
- **Refactor Phase A ships** → §0 becomes "Refactor complete, 5-module structure live, next is Stage 4 Subtractive".

Never accumulate multiple handoff files. Single-item inbox only.
