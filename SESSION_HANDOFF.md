# Session Handoff — 2026-04-16 18:15 KST

> **WHO AM I**: r1000 Quant Engine project (Russell 1000 Top-30 institutional).
> **PURPOSE OF THIS FILE**: shortest possible "pick-up-where-we-left-off" brief for a new Claude / Codex / GPT chat session on a different machine.
> **LIFETIME**: delete / rewrite this file whenever a phase is shipped or a new blocker appears. Do NOT let stale handoff notes accumulate — keep exactly one active handoff.

---

## 1. Last thing that happened

Fixed a critical silent bug: **Phase 2 industry-RS / O'Neil leadership columns were being dropped from `feature_store_latest.parquet`** by the explicit `keep_cols` whitelist in `build_feature_store` (line ~13302 of `r1000_top30_institutional.py`).

- Phase 1 survived by accident (re-derived later in `score_latest_month` / `prepare_latest_scored_data` via `compute_strategy_blueprint_columns`).
- Phase 2 had no re-derivation path → columns missing → `cross_sectional_robust_z` fallback to 0.0 → Phase 2's contribution to sleeve composites was **silently zero** for every walk-forward month AND for the latest scored export.
- **Impact**: every backtest number measured between `2026-04-16 12:36 KST` and `2026-04-16 18:08 KST` was NOT a real "Phase 1+2" measurement — it was "Phase 1 + broken Phase 2 + wasted yfinance fetch".

Commit: `1d4fb40 Fix Phase 2 columns dropped by feature_store keep_cols whitelist` (on `origin/master`).

Changes:
- Added `PHASE2_INDUSTRY_COLUMNS` constant (23 entries: 3 string + 20 numeric).
- Appended it to `build_feature_store.keep_cols`.
- Added numeric-only subset to the `hard_sanitize` call (so `industry` / `industry_group` / `subindustry` stay strings).
- Extended `feature_store` stage coverage report.
- Bumped `ENGINE_REUSE_VERSION` → `"2026-04-16-phase2-keepcols-fix"` (forces feature_store regeneration).
- Updated `CLAUDE.md` and `PHASE_ROADMAP.md` with the new invariant: any new phase adding columns in `build_universe_monthly` MUST also whitelist them in `keep_cols`.

---

## 2. What the user must do NEXT (before any new phase work)

**Run a FULL rebuild in Colab** — not QUICK_RESCORE.

1. Open `colab_run.ipynb` on the new machine / Drive.
2. Cell 2 must have:
   - `QUICK_RESCORE_ONLY = False` ← critical
   - `OPTION_1_FULL_REBUILD = True`
   - `PHASE1_ALPHA_ENABLED = 'auto'`
   - `PHASE2_INDUSTRY_ENABLED = 'auto'`
3. Run cells in order: **1 → 2 → 3 → 4 → 5 → 6 → 9 → 10 → 11**.
4. Cell 4 must print `>>> FULL REBUILD MODE: ...` (not `>>> QUICK RESCORE MODE:`).
5. Expected runtime: ~1.5-3 hours (mostly walk-forward + model retraining; yfinance is cached so no re-fetch needed for Phase 2 metadata).

### Verification gates (after the run)

**Cell 9** (Phase 1+2 column populate sanity):
- Phase 1 — `present=True` for all 5 columns, `nonzero_share` > 0.5 for each. (baseline — unchanged from before)
- Phase 2 — **this is the fix verification**:
  - All 15 columns must show `present=True`.
  - `oneil_leadership_score`, `industry_group_strength_score`, `industry_within_leader_rank`, `industry_rotation_signal`, `rs_industry_6m`, `rs_industry_group_6m` — must have `nonzero_share` ≥ 0.5 (these are the ones that feed sleeve composites at lines 17427 / 17465-17468 / 17506-17509).
  - `industry` / `industry_group` / `subindustry` — strings, `nonzero_share` = fraction of rows with a non-empty string, should be ≥ 0.8.
  - If `[WARN] Phase 2: these columns exist but are all-zero/all-empty` appears → the fix didn't take. Check that the commit is actually pulled (Colab cell 2 should reset `--hard origin/master`).

**Cell 10** (baseline vs new):
- Baseline is still `2026-04-15 pre-Phase1+2`: CAGR 21.80%, Sharpe 0.73, MaxDD -36.86%, `selected_names=2`.
- The **concentrated** comparison is not apples-to-apples if `selected_names` differs. That's expected — ignore the concentrated CAGR delta if `selected_names` changed.
- Report the **diversified (main) portfolio** metrics from the `rebalance_interval_comparison_snapshot` printed at the end of cell 4. Previous run's diversified metrics showed Sharpe 0.73 → 0.99, MaxDD -36.86 → -26.54% (measured BEFORE the Phase 2 fix — so those numbers are still "Phase 1 only + sleeve re-weight", not true Phase 1+2). The true Phase 1+2 diversified metrics come from this new FULL run.

**Cell 11** (top 30 with industry context):
- `industry`, `industry_group`, `oneil_leadership_score`, etc. columns must appear in the display (previously said `[INFO] these requested columns are not present in top30_latest.csv: [...]` — that message should now be empty or only list columns that are genuinely optional).

---

## 3. What's next AFTER the FULL rebuild verifies the fix

Follow `PHASE_ROADMAP.md` §3 (Implementation Order & PR Plan).

If the verification passes, the ordered PR plan is:

1. **Phase 3** — sleeve weight renormalization + phase contribution audit
2. **Phase 4** — regime-conditional dynamic sleeve weights
3. **Phase 5** — sub-industry leader/laggard pair
4. **Phase 6a** — drawdown breaker
5. **Phase 6b** — VIX guard + yield curve
6. **Phase 6c** — vol targeting

Each phase has its own A/B toggle (`PHASE_PHASE<N>_<NAME>_ENABLED=0|1|auto`), its own ship gate (`ΔCAGR ≥ +0.5pp` for offensive phases, `ΔSharpe ≥ +0.1 AND ΔMaxDD ≤ -5pp` for Phase 6 tail protection), and its own CHANGELOG entry. Do not skip phases.

**If Phase 2 verification fails** (columns still missing) — do NOT proceed to Phase 3. Root-cause the whitelist issue again. Likely culprits: (a) Colab didn't `git pull` the fix (check cell 2 output), (b) `feature_store_latest.parquet` was reused from an old cache (check `ENGINE_REUSE_VERSION` in the pipeline log), (c) a second whitelist somewhere downstream that we missed.

---

## 4. Bootstrap prompt for a new chat session

Paste this into a fresh Claude chat on the new machine (or Colab) after cloning the repo:

```
I'm continuing work on the r1000 Quant Engine project. Before doing anything else, please:

1. Read `CLAUDE.md` — project basics.
2. Read `SESSION_HANDOFF.md` — current pending work (THIS is the most important file for picking up where we left off).
3. Read the last ~200 lines of `CHANGELOG.md` — most recent decisions.
4. Read `PHASE_ROADMAP.md` §3 (PR plan) and §5 (invariants) — what's next.
5. Check `git log --oneline -5` to confirm the latest commit is `1d4fb40 Fix Phase 2 columns dropped by feature_store keep_cols whitelist` (or newer).

Only after reading those files, ask me what I want to do next. Do NOT start editing anything until you've read them.

Context: last session (2026-04-16 evening KST) I pushed a critical bug fix that forces a FULL rebuild in Colab. I may or may not have run the FULL rebuild yet — ask me which state I'm in before planning next steps.
```

---

## 5. Files that persist across machines

Everything important is in git, pushed to `origin/master`:

- `r1000_top30_institutional.py` — engine
- `r1000_data_collector.py` — collector
- `colab_run.ipynb` — runbook
- `CLAUDE.md` — project brain (short)
- `PHASE_ROADMAP.md` — phase plan (long)
- `CHANGELOG.md` — decision log
- `SESSION_HANDOFF.md` — this file
- `PROPOSAL_defensive_upgrades.md` — Phase 6 design
- `PROPOSAL_growth_regime_offense_defense.md` — Phase 4 design reference

What's NOT in git (lives only on Google Drive, accessible from any Colab session that mounts the same Drive):

- `cache_*/`, `feature_store/`, `checkpoints/` — cached artifacts (regenerated on FULL rebuild)
- `outputs/` — backtest results, CSV/JSON artifacts
- `companyfacts.zip`, raw SEC / yfinance caches

So: any machine with (a) the GitHub repo cloned and (b) Google Drive mounted to the same account has the full state.

---

## 6. How to delete this handoff

When the Phase 2 verification passes AND you've started Phase 3:

1. Replace this file's content with the new session handoff (new "last thing that happened" = Phase 2 verified + Phase 3 started).
2. OR delete this file entirely and rely on CHANGELOG + PHASE_ROADMAP (if no fresh handoff is needed).

Never accumulate multiple handoff files. This is a single-item inbox, not a log.
