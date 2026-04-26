# Phase 14 Verdict Procedure (FULL Rebuild → SHIP/REGRESS Decision)

How to validate Phase 14 (hybrid alpha) + r1000+adr universe before
rotating CURRENT_BASELINE. **All steps are user-triggered manually**
(claude code in this sandbox cannot execute GitHub Actions workflows).

---

## Pre-flight checklist (already complete as of 2026-04-26)

- ✅ smoke test 56/56 PASS (`py -3 tests/smoke_test.py`)
- ✅ audit_features 3/3 PASS, 238 features, 0 leakage (`py -3 tests/audit_features.py --no-runtime`)
- ✅ Phase 14 PIT-safe (no r_*m / bench_r_*m / earn_post_ / future_* refs)
- ✅ NaN robustness verified (empty / sparse / all-NaN inputs all return neutral)
- ✅ Call order verified (`merge_benchmark_relative_features` line 6442 BEFORE `compute_rs_acceleration_score` line 7043)
- ✅ ENGINE_REUSE_VERSION bumped to `2026-04-25-phase14-hybrid-alpha`
- ✅ All 7 GitHub Actions workflows present and tested

---

## Step 1 — Trigger FULL rebuild (variant: r1000+adr)

```
GitHub UI → Actions tab → "Full Rebuild (Manual / Long-Run)" → Run workflow
  Branch:           claude/analyze-updated-code-OfEbu
  universe_mode:    r1000+adr           ← Phase 14 + ADR enabled
  skip_collector:   true                ← reuse cached prices/SEC/macro
  cache_key_suffix: phase14-variant     (optional, keeps cache separate)
  → Run workflow
```

Estimated runtime: ~3-5 hours (within 6h GHA timeout).
Telegram alert fires at completion with verdict line + run URL.
Artifacts uploaded with 365-day retention.

---

## Step 2 — Trigger FULL rebuild (baseline: r1000-only, control)

Same procedure but:
```
  universe_mode:    r1000               ← R1000-only baseline (no ADRs, Phase 14 still active)
  cache_key_suffix: phase14-baseline    (separate cache from variant)
```

This is the control. Compare CAGR/Sharpe/MaxDD against the variant to
isolate the impact of ADR addition specifically.

**Optional 3rd run** for total isolation:
```
  universe_mode:    r1000+adr_phase14_off   ← ADRs WITH Phase 14 disabled
```
This isolates ADR-only contribution vs. Phase 14-only contribution.

---

## Step 3 — Compare verdicts via tools/compare_adr_backtest.py

After both runs complete and commit `cloud_results/full_rebuild/<date>_<mode>/backtest_metrics.json`:

```bash
# Local (after git pull):
py -3 tools/compare_adr_backtest.py \
  --baseline cloud_results/full_rebuild/<date>_r1000/backtest_metrics.json \
  --variant  cloud_results/full_rebuild/<date>_r1000+adr/backtest_metrics.json
```

Output:
```
CAGR    22.91%  ->    24.50%   ΔCAGR  +1.59pp  (gate ≥ +0.50pp)
Sharpe  1.172   ->    1.200    ΔSharpe +0.028  (gate ≥ -0.050)
MaxDD  -26.26%  ->   -24.00%   ΔMaxDD +2.26pp  (gate ≥ -3.00pp)
VERDICT: ✅ SHIP / 🟡 PARTIAL / ❌ REGRESS
```

Exit codes: 0=SHIP, 1=REGRESS, 2=PARTIAL.

---

## Step 4 — Decision tree

### 4a. ✅ SHIP verdict
1. Edit `run_local.py` `CURRENT_BASELINE` dict to reflect new metrics:
   ```python
   CURRENT_BASELINE = {
       "name": "Phase 14 hybrid alpha + r1000+adr (SHIPPED 2026-MM-DD)",
       "cagr": <new_cagr>,
       "sharpe": <new_sharpe>,
       "max_dd": <new_max_dd>,
       ...
   }
   ```
2. Edit `CLAUDE.md` "Current Production Baseline" section with new numbers
3. Add CHANGELOG entry per Agent Update Contract format
4. `py -3 tests/smoke_test.py` (must stay 56/56)
5. Commit + push (next session can use as the new baseline)

### 4b. 🟡 PARTIAL verdict (CAGR or Sharpe borderline; MaxDD ok)
- Investigate which sleeve/regime drove partial pass
- Common causes:
  - China ADRs (BABA/PDD/JD/BIDU/NTES) decorrelated → wait for monthly_ic_monitor
  - Phase 14 H1/H6/Stage 2 weights too low → tune sleeve composition in r1000_signals.py
- Re-run Step 1-3 after tuning; otherwise hold without rotating baseline

### 4c. ❌ REGRESS verdict
- Determine: ADR contribution OR Phase 14 contribution drives regression?
  - Run Step 2's optional 3rd workflow (r1000+adr_phase14_off) to isolate
- If ADR fault: tighten adr_universe.yaml mcap floor ($30B → $50B), or remove
  China ADRs temporarily, retest
- If Phase 14 fault: lower weights of new features in DEFAULT_FEATURES,
  or disable specific signals via env toggle (PHASE14_*_ENABLED=0 future)
- Do NOT rotate CURRENT_BASELINE until verdict flips to SHIP

---

## Operational watch (already running, no action needed)

| Workflow | Schedule | What to expect |
|---|---|---|
| `daily_review.yml` | Mon-Fri 23:00 KST | scanner top-25 commits to cloud_results/scanner/ |
| `paper_executor_dryrun.yml` | Mon-Fri 23:30 + Sat 15:00 KST | Telegram regime + plan |
| `unified_monthly.yml` | 1st+15th 23:30 KST | scored_unified.csv refresh |
| `theme_discovery.yml` | Sun 22:00 KST | Phase 18A clustering |
| `finnhub_weekly.yml` | Mon 22:30 KST | data refresh |
| `monthly_ic_monitor.yml` | 1st 11:00 KST | Telegram if China-IC > US-IC by 0.05+ |
| `layer4_monthly_swap.yml` | 5th 23:00 KST | Telegram dry-run; manual --execute trigger |

---

## Future ADR additions (post-SHIP)

When new ADRs list (e.g., SK Hynix Oct 2026):
1. Update `adr_universe.yaml` watchlist → main list
2. Update `themes.yaml` (add to `semi_memory`, `semi_design_memory`, etc.)
3. `py -3 tests/check_adr_data.py --ticker <SYMBOL>`
4. `py -3 tests/smoke_test.py` (must stay 56/56 or +1 with new guard)
5. Trigger `full_rebuild_manual.yml` with `universe_mode=r1000+adr`
6. Compare verdict; SHIP if pass

Detailed steps in `ADR_PLAYBOOK.md`.

---

## What NOT to do

- ❌ Do not edit CURRENT_BASELINE before Step 4 verdict completes
- ❌ Do not trigger `--execute` on paper_executor_dryrun.yml before reviewing
  one weekday dry-run + verdict (use weekday Telegram alert as sanity check)
- ❌ Do not enable layer4_monthly_swap.yml `--execute` until first 1-2 dry-run
  cycles confirm swap suggestions look reasonable
- ❌ Do not skip pre-flight (`py -3 tests/smoke_test.py` + audit_features) before
  any FULL rebuild — it catches schema/PIT issues that waste 3-5h of GHA time

---

## Quick reference — current state (2026-04-26)

- **HEAD**: `c5ade4c` — Phase 14 + ADR + 6 phase workflows + pre-flight fixes
- **Branch**: `claude/analyze-updated-code-OfEbu` (origin in sync)
- **Smoke**: 56/56 PASS
- **Audit**: 238 features, 0 leakage
- **ENGINE_REUSE_VERSION**: `2026-04-25-phase14-hybrid-alpha`
- **CURRENT_BASELINE (still old)**: Phase 9 C3 — CAGR 22.91% / Sharpe 1.172 / MaxDD -26.26%
- **NEW BASELINE (pending)**: TBD after Step 3 verdict
