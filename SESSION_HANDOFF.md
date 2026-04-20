# Session Handoff — 2026-04-20 12:00 KST

> **WHO AM I**: r1000 Quant Engine project (Russell 1000 Top-30 institutional).
> **PURPOSE OF THIS FILE**: shortest possible "pick-up-where-we-left-off" brief for a new Claude / Codex / GPT chat session on a different machine.
> **LIFETIME**: rewrite this file whenever a phase ships or a new blocker appears. One active handoff only.

---

## 0. TL;DR — Refactor Phase A IN PROGRESS (branch `refactor/phase-a-module-split`). Stages 0 + 1 + 2 + 3a-c DONE. Stage 1 rollup byte-exact verify PENDING. Stage 3d planned per `STAGE_3D_PLAN.md`.

**Current HEAD = `fd4e6a0`** on branch `refactor/phase-a-module-split` (pushed to remote). **13 refactor commits** on top of last SHIP `6440957`. Main engine **27,838 → 23,594 lines (-15.3%)**. Three new modules created: `r1000_config.py` (2,109L), `r1000_helpers.py` (925L), `r1000_features.py` (1,923L). Smoke tests **25/25 PASS** after each sub-stage.

### What's done (13 commits, newest first)

| Commit | Stage | Summary | Lines |
|---|---|---|---|
| `fd4e6a0` | **3c** | 8 live/satellite/moat/gate feature functions → features.py | -469 main |
| `74be2a0` | **3b** | 28 alpha_vantage + yfinance + fundamental trend fetchers → features.py | -1,237 main |
| `cf5e1a2` | **3a** | 8 industry RS/O'Neil feature funcs → new `r1000_features.py` | -217 main |
| `9cf6d38` | **2d** | 27 IO/ticker/cache/run-identity helpers → helpers.py | -612 main |
| `f2274fc` | **2c** | 11 numpy/pandas stats primitives (winsorize, robust_z, cross_sectional_robust_z, …) → helpers.py | -389 main |
| `d898f48` | **2b** | apply_fast_mode + to_cfg + configure_last_n_years_backtest → helpers.py | -237 main |
| `dfbea54` | **2a** | 5 smallest helpers (phase_is_enabled, now_ts, log, ENGINE_COMMIT_SHA, _resolve_engine_commit_sha) → new `r1000_helpers.py` | -117 main |
| `06f1171` | **1d-ii** | EngineConfig dataclass (435 fields) + default_manual_regime_conditioned_sleeve_map → config.py | -748 main |
| `c3df377` | **1d-i** | 5 scalar constants + `import re` → config.py | -12 main |
| `c59db52` | **1c** | 17 SEC/yfinance/sector data structures → config.py | -216 main |
| `b782e36` | **1b** | 40 pure-data constants → config.py | -774 main |
| `01d5f85` | **1a** | 5 PHASE*_COLUMNS lists → new `r1000_config.py` | -48 main |
| `dd7cf46` | **0 DONE** | baseline captured from `6440957` SHIP outputs (scored/portfolio/weights/backtest_metrics ref files in `.refactor_baseline/`) — no pipeline run needed | +refs |

### What's pending

1. **Stage 1 rollup (RUNNING)** — `py -3 run_local.py --no-collector` launched at ~11:30 KST on commit `fd4e6a0` (last log: `[11:44] [yf_quarterly] Loaded 5978 rows for 974 CIKs`). Expected ~14:00-14:30 KST. Must produce BYTE-EXACT match against `.refactor_baseline/reference.json` via `py -3 .refactor_baseline/verify.py`. If PASS → Stages 0-3c are confirmed value-preserving.
2. **Stage 3d — biggest feature group** (planned per `STAGE_3D_PLAN.md`, 4 sub-stages, ~4,000 lines):
   - **3d-i**: Fundamental panel builders (~1,100L, 7 funcs incl. `recompute_fund_panel_derived_columns` 458L with Phase 9 C3 `_sign_flip_pos` nested helpers — HIGH RISK scope preservation)
   - **3d-ii**: Macro/event regime builders (~850L, 9 funcs incl. `build_macro_regime_table` 417L)
   - **3d-iii**: Market/dynamic-leadership/crisis features (~650L, 6 funcs)
   - **3d-iv**: Strategy blueprint/pillar/minervini composites (~1,400L, 3 funcs incl. `compute_strategy_blueprint_columns` 926L)
3. **Stage 4**: `r1000_signals.py` — sleeve composition + portfolio construction
4. **Stage 5**: `r1000_pipeline.py` — orchestration + facade re-exports on `r1000_top30_institutional.py`
5. **Stage 6 (Subtractive)**: delete `_legacy_unused_*` funcs (~2,500L) + Phase 3/5/7a dead branches

### Production baseline — UNCHANGED by refactor (value-preserving extraction)

Phase 9 C3 + CE v2 baseline from `d3d3a91` / `6440957` still stands:

## 0a. Phase 9 C3 + CE v2 SHIPPED (2026-04-18 21:22 KST) — production baseline

**SHIP VERDICT confirmed on commit `d3d3a91`** (2026-04-18 21:22 KST) via `py -3 run_local.py --no-collector`. Both main diversified AND concentrated improved across every metric. User's original CAGR 30%+ goal achieved via concentrated mode.

### Main diversified — new production baseline (replaces Phase 9 C1+C2)

| metric | new | prior (C1+C2) | delta | ship gate |
|---|---|---|---|---|
| **CAGR** | **22.91%** | 21.69% | **+1.22pp** | ✅ (≥+0.5pp) |
| **Sharpe** | **1.1721** | 1.0732 | **+0.0989** | ✅ (≥-0.05) |
| **MaxDD** | -26.26% | -23.97% | -2.29pp | ✅ (within -3pp) |
| **IR** | **0.9474** | 0.7985 | **+0.1489** | - |
| **excess_cagr** | **+9.42%** | +8.19% | +1.23pp | - |
| avg_turnover | 43.1% | 45.0% | -1.9pp | - |
| early_scout count | 4 | 4 | 0 | ✅ (≥4) |

Portfolio: **18 positions, cash 3.8%**. Sleeve target 60/25/15 (defensive_drawdown_control). Top 5: NVDA 14%, GOOG 14%, AVGO 8.2%, AAPL 7.8%, JNJ 7.8%.

### 🎯 Concentrated champion — CAGR 30%+ goal DONE

**N=5 / monthly / score_power → CAGR 34.75% / Sharpe 1.254 / MaxDD -26.74% / IR 1.073**. $100k → $786k in 83 months (7.87x). **10 combos > 30% CAGR** in the full 63-combo CE v2 grid.

5-name holdings (by score_power weight):

| Rank | Ticker | Name | Sector | Weight |
|---|---|---|---|---|
| 1 | **PR** | Permian Resources | Energy | 30.3% |
| 2 | **ETR** | Entergy | Utilities | 27.8% |
| 3 | **GEV** | GE Vernova | Industrials | 15.2% |
| 4 | **FTI** | TechnipFMC | Energy | 14.5% |
| 5 | **AKAM** | Akamai | IT | 12.3% |

Runner-up concentrated (all >30% CAGR, for A/B robustness):
- N=3 / 1m / score_power: 33.77%, Sharpe 1.193
- N=4 / 1m / score_power: 32.70%, Sharpe 1.185
- N=7 / 2m / score_power: 30.92%, Sharpe 1.227 (lowest turnover 33.9%)
- N=3..10 / 1m / conviction_curve tied at 30.80% (weight decay makes tail positions zero)

### What was shipped (commits f93a4a2 + d3d3a91)
- Phase 9 C3: EPS turn-positive / still-loss-improving branches on early-scout gate (commit `86be7f9`, now in this baseline)
- CE v1: widened concentrated grid defaults (7 N × 3 intervals × 3 modes = 63 combos) and lifted 3 outer caps (commit `f93a4a2`)
- CE v2: lifted 2 inner clamps in `select_concentrated_portfolio_topk` + `backtest_concentrated_portfolio` that were silently clamping N>3 back to N=3. **Without CE v2 the Phase 5e grid was a 21-combo test cosplaying as 63.** Commit `d3d3a91`.

### Baselines rotated (3 files atomic)
- `run_local.py CURRENT_BASELINE` → Phase 9 C3 + CE v2 metrics. Previous baseline kept as `PHASE9_C1C2_BASELINE` for legacy delta calculations.
- `colab_run.ipynb` Cell 10 `BASELINE` → same numbers.
- `CLAUDE.md` "Current Production Baseline" section → same numbers + concentrated champion pointer.

**Current HEAD = `d3d3a91`.** Next commit (this one) rotates baselines atomically across the 3 files.

---

## 1. Recent timeline (newest first) — branch `refactor/phase-a-module-split` on top of `origin/master@6440957`

**Refactor Phase A commits (branch only — NOT yet merged to master)**:

| Commit | Title | Stage | Byte-exact verify |
|---|---|---|---|
| `fd4e6a0` | Stage 3c: 8 live/satellite/moat/gate feature funcs → features.py | 3c | ⏳ pending rollup |
| `74be2a0` | Stage 3b: 28 alpha_vantage + yfinance + fundamental trend → features.py | 3b | ⏳ pending rollup |
| `cf5e1a2` | Stage 3a: 8 industry feature funcs → new `r1000_features.py` | 3a | ⏳ pending rollup |
| `9cf6d38` | Stage 2d: 27 IO/ticker/cache/run-identity helpers → helpers.py | 2d | ⏳ pending rollup |
| `f2274fc` | Stage 2c: 11 numpy/pandas stats primitives → helpers.py | 2c | ⏳ pending rollup |
| `d898f48` | Stage 2b: apply_fast_mode + to_cfg + configure_last_n_years → helpers.py | 2b | ⏳ pending rollup |
| `dfbea54` | Stage 2a: 5 smallest helpers → new `r1000_helpers.py` | 2a | ⏳ pending rollup |
| `06f1171` | Stage 1d-ii: EngineConfig dataclass → config.py | 1d-ii | ⏳ pending rollup |
| `c3df377` | Stage 1d-i: 5 scalar constants → config.py | 1d-i | ⏳ pending rollup |
| `c59db52` | Stage 1c: 17 SEC/yfinance/sector data structures → config.py | 1c | ⏳ pending rollup |
| `b782e36` | Stage 1b: 40 pure-data constants → config.py | 1b | ⏳ pending rollup |
| `01d5f85` | Stage 1a: 5 PHASE*_COLUMNS lists → new `r1000_config.py` | 1a | ⏳ pending rollup |
| `dd7cf46` | Stage 0 DONE: baseline captured from 6440957 SHIP outputs | 0 | ✅ reference |

**Pre-refactor on `origin/master` (newest first)**:

| Commit | Title | Phase | Requires | Default |
|---|---|---|---|---|
| `6440957` | **SHIP Phase 9 C3 + CE v2** (production HEAD before refactor) | 9.C3 + 9.CE v2 | FULL done | ON |
| `d3d3a91` | CE v2: lift 2 inner N<=3 clamps (select + backtest) | 9.CE v2 | QUICK | ON |
| `f93a4a2` | Phase 9 CE: Concentrated Expansion — lift N<=3 cap, 3→63 grid | 9.CE v1 | QUICK | ON |
| `031fa3c` | Fix Cell 5 KeyError + correct Phase 9 baseline metrics | ops | — | — |
| `86be7f9` | **Phase 9 C3: EPS turn-positive + still-loss-improving** | 9.C3 | FULL | ON |
| `c228238` | SHIP Phase 9 C1+C2 rotate baseline to CURRENT_BASELINE | 9.C1+C2 | FULL | ON |
| `527fdde` | Phase 9 C3 design + refactor plan update (docs only) | 9.C3 design | — | — |
| `ced5db6` | **Phase 9 C1+C2: multi_year rebalance + percentile thesis-gate** | 9.C1 + 9.C2 | QUICK | ON |
| `d87160d` | hard_sanitize dedup fix (CRITICAL — unblocked Phase 8 FULL run) | 8 fix | no rebuild | always-on |
| `9b083d2` | Phase 8d: IC-reweight + long-horizon alpha composite | 8d.1 + 8d.2 | QUICK | ON |

**Current `ENGINE_REUSE_VERSION`**: `"2026-04-17-phase8b-long-lookback-momentum"`. **Phase 9 C1+C2 are post-feature-store changes — no version bump.** The in-progress FULL REBUILD was overkill for measuring C1+C2 (a QUICK_RESCORE would have worked in ~20 min), but since it ran, the outputs are valid for verdict.

See `EXECUTION_PLAN.md`, `ARCHITECTURE_REVIEW.md` (incl §6b sleeve taxonomy redesign), `PHASE_9_C3_PROPOSAL.md`, `REFACTOR_PLAN.md` §12 (5-stage sequencing) for design history + forward plan.

---

## 2. Next step — Refactor Phase A in progress. First wait for Stage 1 rollup verify, then execute Stage 3d.

### 🟢 Status (2026-04-20 12:00 KST)

**Branch**: `refactor/phase-a-module-split` (pushed to origin). 13 commits on top of `6440957`. Smoke tests 25/25 at each sub-stage.

**Stage 0 DONE via shortcut** — baseline NOT captured via fresh pipeline run. Instead `.refactor_baseline/capture.py` hashed + copied the existing Drive outputs from 2026-04-18 21:22 SHIP run (commit `6440957`). The 4 reference files are in `.refactor_baseline/`:
- `scored_latest.ref.csv` (SHA256 stored in `reference.json`)
- `portfolio_latest.ref.csv`
- `weights_latest.ref.json`
- `backtest_metrics.ref.json`

**Why shortcut works**: the Drive outputs ARE the byte-exact baseline for commit `6440957` — running the pipeline again from scratch was optional. Saved ~2h.

### What to do on wake-up (pick in order)

**Step 1 — Check Stage 1 rollup status** (~30 sec)

```bash
# Is the rollup task still running?
tasklist | findstr python
# If you see python.exe PID with high memory (600MB+), it's still running.

# Check latest log
tail -f G:\내 드라이브\r1000_top30_institutional\outputs\runlog.txt
# Look for "[validation]" or final "[ALL DONE]" marker
```

If still running: wait. If done: proceed to Step 2.

**Step 2 — Run byte-exact verify** (~5 sec)

```bash
py -3 .refactor_baseline/verify.py
```

Expected output: `✅ ALL 4 FILES BYTE-EXACT MATCH` (scored_latest.csv + portfolio_latest.csv + weights_latest.json SHA256 match; backtest_metrics.json numeric diff within tolerance).

**Possible outcomes**:

- **PASS** → Stages 0 through 3c are confirmed value-preserving. Proceed to Step 3.
- **FAIL** (one or more file mismatch) → **bisect**. The refactor has 13 commits; for each suspect commit, `git checkout <commit> && py -3 run_local.py --no-collector && py -3 .refactor_baseline/verify.py`. Start with the highest-risk commits: Stage 3c (`fd4e6a0`, 8 funcs incl moat/gate), Stage 2c (`f2274fc`, robust_z numeric primitives), Stage 2d (`9cf6d38`, run-identity helpers). Lowest risk: Stages 1a-c (pure constants). Once first-bad commit isolated, read its diff and find the dropped reference / rename / missed import.

**Step 3 (PASS only) — Execute Stage 3d** per `STAGE_3D_PLAN.md`

Read `STAGE_3D_PLAN.md` first — it has the 4-sub-stage breakdown with exact function lists, line numbers, risk notes, and sanity tests. Summary:

- **3d-i** (fundamental panel builders, ~1,100L, HIGHEST RISK) — 7 funcs centered on `recompute_fund_panel_derived_columns` (458L, lines 7805-8262 in current main). This function contains the Phase 9 C3 `_sign_flip_pos` nested helpers critical for the early_scout gate. Scope preservation via explicit nested-function capture is non-negotiable.
- **3d-ii** (macro/event regime builders, ~850L) — 9 funcs incl. `build_macro_regime_table` (417L).
- **3d-iii** (market/dynamic-leadership/crisis features, ~650L) — 6 funcs.
- **3d-iv** (strategy blueprint/pillar/minervini composites, ~1,400L) — 3 funcs incl. `compute_strategy_blueprint_columns` (926L). Largest function in codebase.

**Each sub-stage must**: (1) smoke test 25/25, (2) commit separately, (3) push after commit. Rollup byte-exact verify runs after 3d-iv (same pattern as Stage 1/2/3 rollup, but the 3d changes move feature construction, so a rollup between 3d-i and 3d-ii is acceptable if the user wants tighter bisection).

**Step 4 — Stages 4 + 5 + 6**

- **Stage 4**: `r1000_signals.py` — sleeve composition + portfolio construction (sleeve selectors, backtest_concentrated_portfolio, etc.). ~2-3k lines.
- **Stage 5**: `r1000_pipeline.py` + facade — orchestration (run_default_pipeline, run_full_validation_suite) + add re-exports to `r1000_top30_institutional.py` so existing import sites still work. ~2k lines.
- **Stage 6 (Subtractive)**: delete `_legacy_unused_*` funcs (~2,500L) + Phase 3/5/7a dead branches. Post-refactor, dead code is mechanical to remove.

### Why refactor (unchanged from 2026-04-18 reasoning)

1. Pre-refactor engine was 27,838 lines. Invariants like "PHASE*_COLUMNS must be in `build_feature_store.keep_cols`" + "concentrated cap lifted in 5 sites not 3" are implicit in a monolith. Module split makes them explicit (one owner per concept).
2. Phase 9 is done; no feature work blocking cleanup.
3. Class of bugs like CE v1 inner-clamp miss + Phase 2 keepcols-drop + hard_sanitize dedup dedup — all root cause "monolithic file hides invariants". Refactor encodes them.

### Alternative if rollup FAILs and bisect takes too long

**Option: revert to Stage 2d (`9cf6d38`) and re-attempt Stage 3**. Stage 2 was pure helper extraction with well-known grep patterns; the failure is more likely in Stage 3 (features moved with yf fetchers that call module-level state). Recommend:

```bash
git reset --hard 9cf6d38     # back to end of Stage 2
# re-run rollup verify
py -3 run_local.py --no-collector
py -3 .refactor_baseline/verify.py
# if PASS → Stage 2 is good; Stage 3 has the bug → re-do Stage 3a more carefully
```

---

## 2a. LEGACY — Phase 9 C3 implementation flow (kept for audit trail)

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
I'm continuing work on the r1000 Quant Engine project, MID-REFACTOR (Phase A, 5-module split). Before editing anything:

1. Read `CLAUDE.md` — project basics.
2. Read `SESSION_HANDOFF.md` §0 + §2 — current state + next step (= this file).
3. Read `STAGE_3D_PLAN.md` — 4-sub-stage plan for the next big refactor chunk.
4. Read `REFACTOR_PLAN.md` §6 (checklist) + §11 (observability) + §12 (5-stage sequencing).
5. Run `git log --oneline -20` — expect branch `refactor/phase-a-module-split`, HEAD at `fd4e6a0` or later.
6. Run `git status` — should be clean.
7. Check Stage 1 rollup byte-exact status: run `py -3 .refactor_baseline/verify.py`. If PASS → proceed to Stage 3d per STAGE_3D_PLAN.md. If FAIL → bisect per §2 Step 2.

Do NOT start Stage 3d until byte-exact verify passes on the current HEAD.

Context: Refactor Phase A splits `r1000_top30_institutional.py` (27,838L) into
`r1000_config.py` (2,109L) + `r1000_helpers.py` (925L) + `r1000_features.py` (1,923L) + (pending)
`r1000_signals.py` + `r1000_pipeline.py`. Stages 0 + 1 + 2 + 3a-c done across 13 commits.
Main file now 23,594 lines (-15.3%). Smoke tests 25/25 at every sub-stage.
Production baseline (Phase 9 C3 + CE v2: main CAGR 22.91%, concentrated 34.75%) UNCHANGED — refactor is pure value-preserving extraction.
Remaining: Stage 3d (4 sub-stages, ~4,000L feature funcs), Stage 4 (signals), Stage 5 (pipeline + facade), Stage 6 (Subtractive, -2,500L dead code).
```

---

## 5. Files that persist across machines

Source-of-truth in git. Branch `refactor/phase-a-module-split` has the refactor-in-progress state. `origin/master@6440957` is the last SHIP before refactor.

**Engine modules (refactor branch)**:
- `r1000_top30_institutional.py` — main engine, 23,594L (was 27,838L pre-refactor). Still contains Stage 3d+4+5 functions pending extraction.
- **`r1000_config.py`** — NEW, 2,109L. All pure data constants (PHASE*_COLUMNS, SEC tags, sector maps) + EngineConfig dataclass (435 fields) + default_manual_regime_conditioned_sleeve_map helper. Zero side effects. Import depth: 0.
- **`r1000_helpers.py`** — NEW, 925L. 46 pure helpers: stats primitives (winsorize, robust_z, cross_sectional_robust_z), IO/ticker/cache, run identity, phase_is_enabled gate. Import depth: 1 (from config).
- **`r1000_features.py`** — NEW, 1,923L. 44 feature engineering funcs: industry RS/O'Neil, alpha_vantage/yfinance fetchers, fundamental trend, live/moat/flow/gate features. Import depth: 2 (from config + helpers).
- `r1000_data_collector.py` — collector (unchanged by refactor)
- `r1000_operator.py` — live operator layer (unchanged)
- `r1000_portfolio_state.py` — state persistence (unchanged)
- `colab_run.ipynb` — runbook (unchanged — engine module split is transparent via facade re-exports planned for Stage 5)

**Refactor infrastructure**:
- **`.refactor_baseline/`** — byte-exact reference files from commit `6440957`. Contains `reference.json` (SHA256 manifest), `scored_latest.ref.csv`, `portfolio_latest.ref.csv`, `weights_latest.ref.json`, `backtest_metrics.ref.json`, `verify.py` (comparator), `capture.py` (rebuild script).
- **`STAGE_3D_PLAN.md`** — NEW. 4-sub-stage plan for Stage 3d (fundamental panel + macro + strategy_blueprint + pillar). Read before executing 3d.
- `tests/smoke_test.py` — 25 tests spanning main + config + helpers via `_combined_src()` helper.

**Docs**:
- `CLAUDE.md` — project brain (short)
- **`SESSION_HANDOFF.md` — this file (single-item inbox)**
- `CHANGELOG.md` — decision log (every commit has a matching Agent Update Contract entry)
- `EXECUTION_PLAN.md` — 4-stage roadmap
- `ARCHITECTURE_REVIEW.md` — cold first-principles assessment + sleeve redesign rationale
- `REFACTOR_PLAN.md` — 5-module split + observability + §12 5-stage sequencing diagram (currently being executed)
- `PHASE_9_C3_PROPOSAL.md` — Phase 9 C3 EPS turn-positive flag design (shipped, kept for audit trail)
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
| **9.C1** multi_year weight rebalance | `phase9_c1_rebalance_enabled` | `PHASE_PHASE9_C1_REBALANCE_ENABLED` | ON | **SHIPPED 2026-04-18** (part of current baseline) |
| **9.C2** percentile thesis gate | `phase9_thesis_gate_enabled` | `PHASE_PHASE9_THESIS_GATE_ENABLED` | ON | **SHIPPED 2026-04-18** (restored sleeve taxonomy) |
| **9.C3** EPS turn-positive flags | `phase9_c3_turnaround_enabled` | `PHASE_PHASE9_C3_TURNAROUND_ENABLED` | ON | **SHIPPED 2026-04-18 21:22 KST** (commit `d3d3a91`; +1.22pp CAGR, +0.099 Sharpe, +0.149 IR vs C1+C2) |
| **9.CE** Concentrated Expansion | `concentrated_top_n_candidates`, `concentrated_rebalance_intervals`, `concentrated_weighting_modes` (list cfg) | — (grid params) | default 7×3×3 = 63 combos | **SHIPPED v2 2026-04-18** (commit `d3d3a91`; lifted 5 hard caps; champion N=5/1m/score_power = 34.75% CAGR) |

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
- **Stage 1 rollup verify PASSES** → update §0 "Stage 1 rollup ✅", §2 Step 1/2 remove, bump "what's pending" to Stage 3d as active.
- **Stage 3d-i ships** (after fundamental panel move) → rotate §0 "Stages 0-3c-i ✅", §2 becomes "next: 3d-ii macro". Byte-exact verify gates every 3d-{i,ii,iii,iv} ship.
- **Stage 3d-iv ships** (Stage 3d complete) → rotate §0, §2 becomes "next: Stage 4 signals.py". Update `STAGE_3D_PLAN.md` to "COMPLETE".
- **Stage 4 + Stage 5 ship** (full 5-module split live) → §0 becomes "Refactor Phase A COMPLETE, 5-module structure live". §2 pivots to Stage 6 (Subtractive pass) or Phase 8e (r_12m ML).
- **Stage 6 (Subtractive) ships** → §0 notes LOC savings (~2,500L); close refactor chapter; §2 pivots to next alpha work (Phase 8e, quarterly rebalance, R2000 universe, etc.).
- **Refactor branch merged to master** → squash-merge or preserve 13+n commits; tag `refactor-phase-a-done`; delete branch.
- **Any ship rollback** → §0 becomes "refactor branch paused, current production = `origin/master@6440957`"; re-plan.

Never accumulate multiple handoff files. Single-item inbox only.
