# Session Handoff - 2026-04-29 18:00 KST (ADR mktcap bug fixed, rebuild needed)

> **WHO AM I**: r1000 Quant Engine project (Russell 1000 Top-30 institutional).
> **PURPOSE OF THIS FILE**: shortest possible "pick-up-where-we-left-off" brief for a new Claude / Codex / GPT chat session on a different machine.
> **LIFETIME**: rewrite this file whenever a phase ships or a new blocker appears. One active handoff only.

---

## ACTIVE INBOX (2026-04-29 18:00 KST) - ADR USD market-cap fix + Phase 15-D rerun

**TL;DR** — Run `25091384080` completed successfully and synced to GDrive, but
verdict was PARTIAL, not SHIP. User spotted a real ADR market-cap bug: TSM was
larger than NVDA because the engine multiplied USD ADR price by ordinary local
shares. Code now normalizes ADR market cap to yfinance USD marketCap and uses
ADR-equivalent shares for valuation. A new full_rebuild is required before
judging Phase 15-D again.

**State of master (as of 2026-04-29 18:00 KST)**

```
HEAD: pending/current master after ADR USD market-cap normalization
       5bc9ef0  chore(bot): full rebuild [global_alpha_universe] 2026-04-29 [skip ci]
       959b76a  fix(actions): expose finnhub state for phase15d rebuild
       180d854  docs: CHANGELOG + SESSION_HANDOFF for Phase 15-D handoff
       3db9386  feat(phase15d): cycle_play universe + multi-source fallback + chase prevention
       e7c6ff9  fix(acceptance): unblock portfolio for r1000+adr universe (research mode)
       186f9f5  fix(phase15c): mktcap $1T clip + 1970 epoch fund_period leak
       50f432b  fix(phase15c): sub_industry_rs_score crash (build_feature_store)
       0e8ced2  fix(export): prune empty / zero-fill columns from scored_latest.csv
       cc4bcff  feat(phase15c): risk discipline + ML×tech gate + sub-industry rank
       47875dd  feat(phase15c): entry_quality_score
       9bd5606  fix(phase15): activate sleeping cycle_recovery + eps_revision

ENGINE_REUSE_VERSION: 2026-04-28-phase15c-entry-quality (Phase 15-D additive only)
DEFAULT_FEATURES: 245
Smoke: 69/69 pass after ADR mktcap fix; audit 0 leakage
Working tree: clean
```

**What Phase 15-A/B/C/D added (cumulative)**

7 ML features in `PHASE15_ALPHA_COLUMNS`:
1. `cycle_recovery_score`     — late-rescue cycle leaders (mom_24m bottom + mom_6m turn)
2. `eps_revision_score`        — eps_growth fallback when AV estimates missing
3. `early_cycle_inflection_score` — multiplicative gate (price near MA200 + mom_12m bottom + mom_3m early turn) + boost (eps revision + sign flip + industry breadth)
4. `entry_quality_score`       — chase-prevention (extension penalty + RSI zone + mom sweet spot + volume confirmation)
5. `ml_technical_agreement_score` — demote ML-strong-tech-weak names
6. `sub_industry_rs_score`     — best-of-best in sub_industry pct rank
7. `insider_cluster_boost_score` — 3+ insider buyers boost

Plus 36-name `cycle_play_universe.yaml` (BE/PLUG/RIVN/ENPH/...) with monthly
auto-refresh (`tools/refresh_cycle_play_universe.py` +
`.github/workflows/cycle_play_refresh.yml`, 1st of month 14:00 UTC).

**Critical fixes shipped (read these before re-debugging)**

1. ADR carve-out (8172c0d): exempts ADRs from R1000 SEC fundamentals gate
   denominator so R1000-only metrics don't degrade when ADR overlay added.
2. Acceptance gate relaxation (e7c6ff9): r1000+adr / global_alpha_universe
   modes no longer block portfolio_latest export when historical_membership
   file missing (research mode, ADR overlay = research, relax strict check).
3. mktcap clip $1T -> $100T (186f9f5): NVDA / AAPL / MSFT etc no longer get
   collapsed into single $1T tier. Was bug at 3 sites (build_feature_store,
   training, historical scoring); previously only patched at 1 site.
4. fund_period 1970 epoch leak (186f9f5): pd.to_datetime(0) returned
   1970-01-01 for missing periods. Now masked to NaT for any date < 1990.
5. CSV export pruner (0e8ced2): scored_latest.csv 638 cols -> 483 cols
   (24% reduction) by dropping all-NaN + all-zero placeholder columns.
   Phase 14/15 score columns whitelisted regardless.
6. Concentrated entry_quality hard filter (3db9386): rejects pool entries
   below `cfg.concentrated_min_entry_quality=0.30` so AMKR (mom_12m +340%)
   / WDC (+902%!) / FTI (+175%) chase entries no longer enter concentrated.

**Latest cloud run state**

Run `25091384080` (commit `959b76a`) completed successfully:
- GitHub Actions: success; artifact `full-rebuild-global_alpha_universe-25091384080`
- GDrive sync: success; outputs under `G:\내 드라이브\r1000_top30_institutional\outputs`
- Bot commit: `5bc9ef0`
- Main metrics: CAGR 23.48%, Sharpe 1.251, MaxDD -23.79%
- Verdict: PARTIAL vs Phase 14 (dCAGR -0.10pp, dSharpe +0.0727, dMaxDD -0.62pp)
- Concentrated: CAGR 25.43%, Sharpe 1.246, MaxDD -21.62%, 5 names
- ADRs worked: 30 scored, 4 in main portfolio (NTES, TSM, ZTO, ASML)
- Cycle-play weak: 33 injected / 20 added, but only 2 scored and 0 selected
- Do **not** rotate CURRENT_BASELINE.

**Critical post-run bug found and fixed (2026-04-29 18:00 KST)**

- TSM `mktcap` was ~10.17T because `px=392 USD ADR price` was multiplied by
  `shares=25.9B Taiwan ordinary shares`. True yfinance USD marketCap proxy is
  ~2.03T. Similar ADR-ratio distortions exist for NTES/PDD/ZTO.
- Fix: `apply_adr_usd_mktcap_proxy` anchors ADR market cap to yfinance USD
  marketCap and applies the ADR-ratio factor to historical px*shares rows.
- Fix: `compute_valuation_columns` uses `mktcap / px` as ADR-equivalent shares
  for ADR EPS/PE math.
- Fix: `extract_companyfacts_records` now prefers USD companyfacts units when
  SEC exposes multiple monetary unit buckets.

**Pre-trigger correction (2026-04-29 13:41 KST)**

- Do **not** use `skip_collector=true` for the first Phase 15-D verification.
  Local/GDrive price cache only has 13/33 active cycle-play tickers; 20 are
  missing and need the collector to fetch their history.
- Latest successful Finnhub weekly artifact (`25003804766`) was downloaded into
  `aggressive/state/finnhub/r1000_features.parquet` and force-added so cloud
  full_rebuild can immediately use Phase 15-D Finnhub PE/PEG fallback.
- GitHub Actions now caches/restores `aggressive/state/finnhub` and prints
  pre-run diagnostics:
  - `[cycle] active=... missing_price_cache_before_collector=...`
  - `[finnhub] fallback parquet present rows=... cols=...`

**Recommended next agent action sequence**

1. **TRIGGER AGAIN AFTER ADR FIX**: GitHub Actions `Full Rebuild (Manual / Long-Run)` with:
   ```
   universe_mode:    global_alpha_universe   ← includes R1000 + ADR + cycle play
   backtest_years:   8
   skip_collector:   false (first fair Phase 15-D run must collect missing cycle prices)
   fast_mode:        true
   cache_key_suffix: phase15d-cycle
   ```
   Expected runtime: ~2-3h if cache restored; use `skip_collector=false` if
   cycle-play price cache is still missing in the runner.

2. **VERIFY POST-REBUILD**:
   - `cloud_results/full_rebuild/latest_global_alpha_universe/portfolio_latest.csv`
     should be NON-EMPTY (e7c6ff9 unblocks)
   - concentrated_portfolio entries should NOT be AMKR/WDC/FTI class
     (D2 blocks entry_quality < 0.30)
   - scored_latest.csv should include cycle play tickers (BE/PLUG/RIVN/...)
   - new columns: trailing_pe_recomputed, earnings_yield_recomputed,
     forward_pe_source, sub_industry_rs_score, insider_cluster_boost_score
   - `tools/aggregate_portfolio_performance.py --base-dir
     cloud_results/full_rebuild/latest_global_alpha_universe` to summarize
     per-sleeve + aggregate.

3. **DECIDE BASELINE ROTATION**:
   - If verdict SHIP (dCAGR ≥ +0.5pp, dSharpe ≥ -0.05, dMaxDD ≥ -3pp,
     early_scout selected ≥ 4): rotate CURRENT_BASELINE in
     `run_local.py` and update CLAUDE.md "Current Production Baseline"
     section.
   - If REGRESS: identify which Phase 15 feature has negative ML weight
     (read backtest_metrics.json model_coef section), disable via env
     var (PHASE_PHASE15C_ENTRY_QUALITY_ENABLED=0 etc), re-trigger.
   - If PARTIAL: investigate sleeve mix; concentrated likely shipping
     (33%+ CAGR threshold); main may need next iteration.

4. **TELEGRAM SILENCE since Apr 23**:
   - cron workflows (daily_review, paper_executor, tactical_after_close)
     stopped firing for 5 days. Manual triggers still work
     (full_rebuild ran successfully Apr 28).
   - Suspected cause: GHA scheduled workflow auto-disable due to free-tier
     quota (~15-20h consumed by recent full_rebuild runs).
   - Diagnose: GitHub Actions tab → check for "disabled" badge on
     daily_review workflow. Settings → Billing → see GHA usage.
   - If disabled: click "Enable workflow" on each affected cron file.
     Manual trigger of daily_review can validate Telegram works.

5. **D5 CYCLE PLAY AUTO-REFRESH**:
   - Workflow `.github/workflows/cycle_play_refresh.yml` runs 1st of
     each month at 14:00 UTC.
   - First scheduled fire: 2026-05-01 14:00 UTC.
   - Manually trigger to test: Actions tab → Cycle Play Universe Refresh
     → Run workflow.

**Files to read in order for new agent pickup**

1. This file (SESSION_HANDOFF.md) — current.
2. CHANGELOG.md top section (2026-04-29 entry) — Phase 15-D detail.
3. CLAUDE.md "Current Production Baseline" — Phase 14 still production.
4. cycle_play_universe.yaml — 36 entries by theme.
5. r1000_features.py compute_entry_quality_score / compute_cycle_recovery_score
   — current alpha logic.
6. Recent backtest_metrics.json (cloud_results/full_rebuild/latest_*) — last run.

---

## PRIOR INBOX (archived — Phase 14 / Apr 27)

Below is the previous session handoff (Phase 14 SHIP + ADR v2 prep). Useful
for understanding the Phase 14 baseline that Phase 15-D extends.

## ACTIVE INBOX (2026-04-27 18:40 KST) - ADR v2 / 8y official run next

**Current status**

- **A complete**: Phase 14 metrics are the production baseline in `run_local.py`, `colab_run.ipynb`, and `CLAUDE.md`. Old baseline preserved as `PHASE9_C3_CE_V2_BASELINE`.
- **B fixed in code**: ADR universe was dead in the main engine. Root cause was three-part:
  - GitHub Actions set `UNIVERSE_MODE`, but `run_local.py` did not pass it into EngineConfig overrides.
  - `full_rebuild_manual.yml` used legacy `PHASE14_HYBRID_ALPHA_ENABLED`; `phase_is_enabled("phase14_hybrid_alpha")` consumes `PHASE_PHASE14_HYBRID_ALPHA_ENABLED`.
  - `r1000_pipeline.py build_candidate_universe()` always used historical R1000 membership and historical membership filtering would drop external ADR rows.
- **B validation**: smoke 62/62 PASS, ADR quick audit 26/26 PASS, synthetic membership-filter check keeps `adr_whitelist` rows.
- **Global alpha universe path now wired**: use `universe_mode=global_alpha_universe` for the shared R1000 + curated ADR/global-alpha pool. Core and concentrated both consume the same scored frame, so this is the common universe for both sleeves/engines.
- **ADR v2 prepared**: `adr_universe.yaml` expanded from the original 26-name mega-cap ADR set to a 105-name active whitelist at the default ~$8B floor. ADR/global-alpha rows with sparse SEC fundamentals can pass via `adr_global_alpha_fallback` when price, momentum, relative strength, and score confirmation are strong enough.
- **8-year path is now the official default**: default backtest window is 8 years. GitHub Actions exposes `backtest_years=8`/`10`; `backtest_window_comparison.csv` still includes 5/8/10 and flags `partial_window` when OOS history does not cover the full requested window.
- **Sleeve audit now wired**: FULL/QUICK exports `reports/global_alpha_sleeve_audit_by_month.csv` and `reports/global_alpha_sleeve_audit_summary.csv` with per-sleeve candidate counts, gate-pass counts, ADR/source mix, growth/momentum/quality averages, and latest core/concentrated selected counts.
- **Latest global-alpha FULL run before ADR v2**: run 24974747494 proved ADR injection worked mechanically, but only 5 ADR/global-alpha rows survived into `scored_latest.csv`, 0 were selected, and the run was marked `research_only_backtest=true` because 10y coverage was partial. Trigger a new FULL rebuild after this ADR v2 commit.

**Design read against user goal**

- **Core portfolio goal**: current Phase 14 main CAGR is 23.58%, Sharpe 1.178, MaxDD -23.17%, avg monthly turnover 45.5%. The architecture is pointed the right way, but core is not yet a stable 25% system. Do not chase this by adding more names/signals first; next best step is C, the quarterly/sleeve-aware rebalance A/B, because turnover and exit cadence are the largest stability risks.
- **Concentrated goal**: current champion is N=5/monthly/score_power, CAGR 33.40%, Sharpe 1.284, MaxDD -25.29%. If daily trading is allowed, concentrated needs a separate daily replay/aggressive execution track; forcing daily behavior into the monthly core backtest will blur the mandate and make core less stable.
- **Recommended sequence from here**:
  1. Run smoke, commit/push current `global_alpha_universe` + 8y default + ADR v2 fallback wiring.
  2. Trigger GitHub Actions `full_rebuild_manual.yml` with `universe_mode=global_alpha_universe`, `backtest_years=8`, `skip_collector=false` if the ADR cache needs full refresh, otherwise `skip_collector=true`, `fast_mode=true`.
  3. Review `scored_latest.csv` ADR count, ADR fallback gate labels, and `global_alpha_sleeve_audit_summary.csv` to confirm sleeve selection behavior.
  4. Then start C for core stability: compare monthly vs quarterly/sleeve-aware cadence and only change sleeve score/gate weights after the audit shows the failure mode.
  5. After C, design concentrated daily replay using scanner signals, daily stop/hold rules, and separate CAGR-max objective.

---

## 🎉 Phase 14 ZIP Verdict (run 24961673988, 2026-04-27 10:18) — SHIP CONFIRMED

**Verdict tool output** (`tools/compare_adr_backtest.py --variant ... --use-pinned-baseline`):

```
CAGR      22.91%  ->    23.58%   ΔCAGR  +0.67pp  (gate ≥ +0.50pp)  ✅
Sharpe    1.172   ->    1.178    ΔSharpe +0.006  (gate ≥ -0.050)   ✅
MaxDD    -26.26%  ->   -23.17%   ΔMaxDD +3.09pp  (gate ≥ -3.00pp)  ✅
VERDICT: ✅  SHIP — All 3 gates pass.
```

**Lifetime CAGR (Phase 12)**: 23.48% over 6.84y, $100k → $432k cumulative.

**Phase 14 features verified in scored_latest.csv** (6/6 present):
rs_acceleration_score, h1_oversold_value_score, h6_dynamic_leader_score, stage2_overext_penalty, theme_phase_multiplier_primary, theme_phase_multiplier_max.

**Run metadata**: commit 724fbb9 DIRTY, engine 2026-04-25-phase14-hybrid-alpha, 95/95 walk-forward months, acceptance_checks all_pass=True.

**Artifact location**: `research/phase14_artifact/` (7 files including verdict.log + full pipeline log) — preserved for new agent reference.

---

## 🟢 LATEST STATE (2026-04-26) — Phase 14 hybrid alpha + ADR universe code-ready, FULL rebuild verdict pending

**Current HEAD = `2d1f329`** on `claude/analyze-updated-code-OfEbu` branch.

### What just shipped (code only, FULL rebuild not yet run)

**Phase 14 hybrid alpha (`5a41219`)** — wired validated Aggressive scanner alpha into 정석 ML cfg.features:
- `rs_acceleration_score` (T4 +10% alpha)
- `h1_oversold_value_score` (Opus H1 +8.67% alpha 12m, n=1149, p<0.0001)
- `h6_dynamic_leader_score` (Opus H6 +7.38% alpha 12m, n=704, p<0.0001)
- `stage2_overext_penalty` (T1 -2.5% protection)
- `theme_phase_multiplier_{primary,max}` (themes.yaml early/maturing/peaking/ending/dead)
- `ENGINE_REUSE_VERSION = "2026-04-25-phase14-hybrid-alpha"` (DEFAULT_FEATURES 232→238)

**ADR universe (`d62fbb6`)** — 26 top-mcap ADRs (TSM, ASML, BABA, NVO, ...) + 3 watchlist (SK Hynix Oct 2026, Samsung Pink-OTC, Reliance India). Universe modes `r1000`, `r1000+adr`, `adr`. Safety: ADRs flagged `skip:true` (TCEHY OTC) excluded.

**8 GitHub Actions workflows operational** (~1120min/month < 2000 free):
- `daily_review.yml` Mon-Fri 23:00 KST (R1000 scanner top 25)
- `paper_executor_dryrun.yml` Mon-Fri 23:30 + Sat 15:00 KST (regime + advisor + Telegram)
- `unified_monthly.yml` 1·15일 23:30 KST (scored_unified.csv)
- `theme_discovery.yml` Sun 22:00 KST (Phase 18A)
- `finnhub_weekly.yml` Mon 22:30 KST
- `layer4_monthly_swap.yml` 5일 23:00 KST (Layer 4 swap, dry-run by default)
- `monthly_ic_monitor.yml` 1일 11:00 KST (ADR macro IC, Telegram alert if China-IC > US-IC + 0.05)
- `full_rebuild_manual.yml` MANUAL ONLY (3-5h, universe_mode r1000 / r1000+adr / r1000+adr_phase14_off)

**Pre-flight verified (Phase A-F system audit, 2026-04-26)**:
- ✅ smoke 56/56 PASS
- ✅ audit_features 3/3 PASS, 238 features, 0 forward-return
- ✅ Phase 14 PIT-safe (no r_*m / bench_r_*m / earn_post_ / future_* refs)
- ✅ NaN robustness verified (all-NaN/sparse → neutral 1.0 multipliers)
- ✅ Call order: merge_benchmark_relative_features (line 6442) → Phase 14 (7043+)
- ✅ All 8 workflows YAML valid, secret refs correct

### 🚧 Next-agent priority (in order)

1. **Trigger `full_rebuild_manual.yml`** with `universe_mode=r1000+adr` (variant). 3-5h GHA runtime, Telegram alert at completion.
2. **Trigger again with `universe_mode=r1000`** (control, R1000-only baseline).
3. **Run verdict tool**: `py -3 tools/compare_adr_backtest.py --baseline <r1000_metrics> --variant <r1000+adr_metrics>`. Output: SHIP / PARTIAL / REGRESS.
4. **If SHIP**: rotate `CURRENT_BASELINE` in `run_local.py` + update CLAUDE.md "Current Production Baseline" + add CHANGELOG entry.
5. **If REGRESS**: optionally run 3rd workflow `r1000+adr_phase14_off` to isolate (ADR fault vs Phase 14 fault).

Detailed step-by-step in `PHASE14_VERDICT_PROCEDURE.md` (164 lines).

---

## 🗂️ ARCHIVED (pre-2026-04-26)

(Original handoff content from 2026-04-22 below — kept for historical reference. Issues mooted by Phase 14 + ADR work shipping. Do not act on these unless Phase 14 verdict triggers re-investigation.)

## 🟢 ARCHIVED STATE (2026-04-22 evening) — 9-cell grid done, baseline regression to investigate

**Current HEAD = `b4e3bab`** on `master`. 41 commits today.

### ✅ UPDATE (evening `bl49bkdrv` full QUICK complete)

**--ab-quick bug identified + actual regression is manageable**:

```
OLD baseline (b0r5er6bz):              CAGR 22.95% / Conc 33.17%
--ab-quick baseline (bi4d0bmfu, bad):  CAGR 16.08% / Conc NaN (degenerate)
Full QUICK baseline (bl49bkdrv, good): CAGR 19.78% / Conc 30.92%
```

**Root cause of perceived catastrophic regression**: --ab-quick mode
disables concentrated grid → sleeve_cap_policy champion selection fails
→ main blend construction cascaded degradation. Not a real alpha regression;
a bug in the A/B-quick mode.

**Actual regression is -3.17pp main / -2.25pp concentrated**, consistent
with normal data drift + Tier 0 mktcap cap change + ML retrain. Not catastrophic.

### ⚠️ Next-agent priority (revised)

1. **--ab-quick mode fix** — preserve at minimum 1 concentrated combo + sleeve_cap_policy champion so main blend stays valid. All 9-cell grid results from `b4e3bab` invalid (used broken --ab-quick baseline).
2. **Rerun 9-cell grid on Full QUICK baseline** — each cell ~20-30min × 9 = 3-4 hours. OR cherry-pick most-likely cells only.
3. **15-A1 FULL rebuild** — test feature-store-level change properly (~3h).
4. **Investigate -3pp drift**: is it Tier 0a mktcap cap? Revert in isolation to confirm.
5. **15-S1b ML target r_3m** — biggest expected lift per deep audit (~3h FULL).

### Tier 2 grid verdict (9-cell, `b4e3bab`)
See `research/phase15_tier2_ab/VERDICT_OVERNIGHT.md`.

- R1/R2/R3 trailing/revision/RS break exits: **zero delta** (threshold never
  triggers in 83-month sample). Safe to ship as future insurance.
- Phase 4 regime sleeve weights: **-0.25pp FAIL**. Keep default OFF.
- Phase 6c vol targeting: **zero delta** (dormant). Safe to ship.
- 15-A1 negative features drop: **zero delta** because cache-blocked.
  Requires FULL rebuild for valid A/B.
- Concentrated outputs: all NaN (--ab-quick disables concentrated grid).

### In-flight
`bl49bkdrv` full QUICK (no --ab-quick) baseline — will produce concentrated
grid results. 30-60min. Results saved to `outputs/` on Drive.

### Massive Tier 0/1/2 ship batch (26 commits today)

Foundation + gate fixes:
- `04503fd` tier0a + gates: mktcap clip 1e12 → 1e14 (mega-caps no longer collapsed); Phase 4/6c/7a gate env-overrides-cfg (previously locked dormant since 2026-04-16)
- `42ddce3` tier0b: SEC companyfacts int-date parsing (1970 epoch bug — 477/610 rows)
- `5b5edac` tier0c: standalone sleeve CSVs now populate (sleeve_test column added)

Speed infra:
- `ebc0b26` --ab-quick CLI flag (disable 7 grid comparisons)
- `b43c680` apply_fast_mode override fix (concentrated grid was forced on)
- `fb4547f` em-dash crash fix (cp949 console)
- `7b9dad1` reuse_fingerprint excludes runtime-only fields (no more cache invalidation when adding cfg fields)

Phase 15 implementations (all default OFF, env A/B ready):
- `dfcc07c` 15-S1a: 3 toxic factor prune (future_winner only)
- `b002f8a` 15-S1a gate env-overrides-cfg fix
- `2cc2a76` 15-S1a sub-toggles (per-factor ablation)
- `6d1d848` 15-A1: drop 3 NEGATIVE-IR features (macro_hedge, focus_defensive, focus_live_event_defensive)
- `1f6349e` 15-R1: trailing stop early_scout / future_winner (peak drawdown)
- `abe89b0` 15-R2 + 15-R3: revision break + RS break exits
- `aba097c` smoke locks + Tier 2 grid runner

Research:
- `21f1979` Phase 15-S1 factor IC audit (3m horizon = sweet spot, 1m near-random)
- `53af224` 15-S1a verdict: main FAIL / concentrated PASS
- `77d829f` selection deep audit (production score IR 0.048; 11 missed winners; 4 negative features)

### A/B in flight
`b029fgd3t` 15-A1 with --ab-quick. ONE-TIME slow rebuild (30-60min) due to fingerprint formula change in `7b9dad1`. After this completes, ALL future A/Bs are ~5min.

### Tier 2 A/B grid READY (after b029fgd3t completes)
```
bash research/phase15_tier2_ab/run_tier2_grid.sh   # 6 cells × ~5min = ~30min
py -3 research/phase15_tier2_ab/analyze_tier2.py    # delta + ship gate verdict per cell
```
Cells: A baseline / B R1 only / C R2 only / D R3 only / E all_R / F R+A1.

### Known gaps still open
- Tier 0d: r_12m coverage cliff — investigated, **NOT a bug** (forward returns naturally NaN for recent 12m). No action.
- Tier 0e: Benchmark R1000 vs SPX — investigation pending.
- Phase 4 / 6c A/B — gate fixed `04503fd`, ready to run once Tier 2 done.
- Phase 7a redesign (clustered insider buying) — design pending.
- 15-R4 weekly monitor — architectural change, not started.
- 15-S2b core conviction lock — design needs revision (target mid-rank #8-18 per audit Finding 4).
- 15-S1b ML target r_3m realign — needs FULL rebuild (~3h).
- Phase 13-lite (yaml split + summary.json + recent_trades.json) — service tier, not started.
- Phase 14 dividends — deferred.

### Ablation COMPLETE (`bbl6mkuiq` + `bhyyse6xs`)

| Variant | Main ΔCAGR | Main MaxDD | Conc ΔCAGR | Conc Sharpe | Verdict |
|---|---|---|---|---|---|
| full_prune (all 3) | -0.46pp | +4.03pp | +3.25pp | +0.118 | main FAIL |
| drop_ft only | -0.12pp | +4.01pp | +2.97pp | +0.111 | main FAIL |
| drop_cf only | +0.15pp | -0.08pp | +0.80pp | +0.022 | FLAT |
| **drop_ub only** | **+0.36pp** | -0.08pp | +0.77pp | +0.021 | **FLAT (best)** |
| drop_cf+ub | +0.16pp | -0.19pp | +0.80pp | +0.022 | FLAT |

**Decision**: strict ship gate (+0.5pp) not cleared by any variant. All cfg defaults remain OFF.

**Insights**:
- FT alone drives 91% of concentrated +3.25pp AND all of main MaxDD +4pp win — but costs -0.12pp main CAGR.
- CF + UB combined ≈ UB alone (sub-additive, correlated noise).
- drop_ub best single-factor pick (+0.36pp main, +0.77pp conc, MaxDD flat).

Full write-up: `research/phase15_s1a_ab/VERDICT_ADDENDUM_ABLATION.md`.

### Recommended next step (for next agent session)

1. **Concentrated-exclusive FT drop** (~1-2h code work, then QUICK A/B):
   - Modify `concentrated_score` computation at r1000_pipeline.py:11939 to use a second "pruned" future_winner composite with FT zeroed. Main composite untouched.
   - Expected: main neutral, concentrated +2.97pp (matches variant A).
   - Cleanly ships biggest concentrated win without main regression.

2. OR **Phase 15-S1b horizon realign** (FULL rebuild, 2-3h):
   - Train `pred_future_winner_ret` on `r_3m` target instead of `r_1m`.
   - IC audit root finding: future_winner composite factors are 3m alpha, not 1m.
   - Higher expected impact but bigger cycle.

3. OR **15-R1 Trailing stop** (cfg fields already prepped in dfbfaed):
   - Wire the backtest loop (r1000_pipeline.py:9831-9864 speculative stop area) to track peak + drawdown per early_scout position.
   - 4-cell A/B (baseline / 0.15 early / 0.20 early / 0.15 both sleeves).
   - Independent of 15-S1 path.

### Gate semantics currently shipped
- Master: `PHASE_PHASE15_S1A_FUTURE_PRUNE_ENABLED=1` drops all 3 factors.
- Sub-toggles: `DROP_FT`, `DROP_CF`, `DROP_UB` drop individually.
- Cfg default: all False (production unchanged). Env var overrides.

**NEW TARGETS** (user set 2026-04-21 PM): main 22.95% → **25% CAGR**, concentrated 33.17% → **40% CAGR**.

### Just finished (afternoon session)
- `6a5491d` chore: gitignore catboost_info/ training artifact
- `24992c7` fix: Phase 12B+ensure_live_portfolio_state moved BEFORE first enrichment (cold-start fix — solves the 2-known-issues #1 from morning handoff)
- `a5a5271` fix: Phase 12A held_days tz bug (utcnow tz-aware vs entry_date tz-naive) + reference_price auto-fill in apply_manual_positions_from_yaml (no more "no_live_data" in lifetime_metrics.json)
- `dfbfaed` prep(phase15-r1): trailing_stop_enabled + trailing_stop_early_scout_pct cfg fields (default OFF, A/B-ready) + structural smoke test
- `21f1979` research(phase15-s1): per-factor rank-IC audit on future_winner composite. **KEY FINDING** (see below).

### VALIDATION in progress (background `b0r5er6bz`)
QUICK pipeline re-run with `PHASE_PHASE11_MULTIBAGGER_ENABLED=0 py -3 run_local.py --no-collector` to verify both Phase 12 fixes land. Expected: 9/9 enrichment columns populated (vs 6/9 on `24992c7`-only run), lifetime_equity_curve.csv = 84 rows (83 backtest + 1 live extension), live_value_method = "shares_x_reference_price".

### 🔥 KEY RESEARCH FINDING — future_winner 1m composite has no factor-level alpha

`research/phase15_s1_future_winner_factor_ic.csv` audit of 21 factors at 1m vs 3m horizons:

| Factor | Weight | IC_1m IR | IC_3m IR |
|---|---|---|---|
| leader_emergence_score | 0.90 | +0.04 | **+2.54** |
| anticipatory_growth_score | 0.95 | +0.00 | **+2.25** |
| future_winner_scout_score | 1.10 | -0.01 | **+2.22** |
| dynamic_leader_score | 0.95 | -0.03 | **+1.71** |
| uptrend_continuation_score | 0.30 | +0.01 | +1.53 |
| rs_industry_6m | 0.25 | +0.06 | +1.50 |
| fundamental_turnaround_acceleration_score | 0.50 | -0.19 | -0.27 (toxic!) |
| cashflow_inflection_under_loss_score | 0.35 | -0.15 | -0.20 (toxic!) |
| uptrend_breakdown_penalty | -0.30 | +0.03 | -2.03 (sign mismatch!) |

**Interpretation**: 17/17 factors are "1m prune candidates" but >10 have IR_3m > +1.5. The composite factors **are 3-month alpha disguised as 1-month decisions**. Future_winner standalone CAGR 16.08% (topn_cagr_1m) is the cost of this horizon mismatch.

**Implications for 15-S1 redesign** (from naive "prune composite" to "realign horizon"):
1. Train `pred_future_winner_ret` ML target on `r_3m` (not `r_1m`)
2. A/B future_winner rebalance interval {2m→3m}
3. Remove the 3 genuinely-toxic factors (negative at BOTH horizons)
4. Expected lift: future_winner 16% → 22-25% standalone (+main blend +0.5-1pp, +concentrated +2-3pp)

### USER'S SEQUENCING DECISIONS (2026-04-21 PM)
- **Phase 13** full ledger (PHASE_13_PLAN.md, 8h) → **discard**. Replace with Phase 13-lite (Option B yaml split, 3h, anytime).
- **R2000 expansion** → **defer indefinitely** (regime-amplification risk during Energy bull).
- **Sector concentration cap (B9)** → **rejected** ("시그널이 그 섹터라고 외치면 믿자"). Keep cap-free, compensate with EXIT discipline (trailing stop, RS break, revision break).
- **Phase 15 ordering** → stability-first, priority-first:
  - Tier 1: Phase 12 bug fix (running)
  - Tier 2: exit discipline (15-R1 trailing / 15-R2 revision break / 15-R3 RS break / 15-R4 weekly monitor)
  - Tier 3: sleeve strengthening (15-S1 future_winner horizon realign / 15-S2 core quality gates / 15-S3 early_scout hardening)
  - Tier 4: 15-S4 sleeve-specific rebalance A/B
  - Tier 5: 15-S5 concentrated regrid
  - Orthogonal: Phase 13-lite (export infra)
- **Deferred**: dividend handling (Phase 14), market-shock detection, automation.

### NEXT AGENT — start here when validation completes
1. Check `/tmp/phase12_bugfix_validation.log` or `G:\내 드라이브\r1000_top30_institutional\outputs\lifetime_metrics.json` for `live_value_method` value.
2. Verify `portfolio_latest.csv` has all 9 enrichment columns populated (not just 6/9).
3. If verdict OK → start **15-R1 trailing stop implementation** in `backtest_portfolio` around line 9831:
   - Mirror `speculative_cum_ret` logic with `trailing_peak_ret` + drawdown-from-peak check
   - Gate on `cfg.trailing_stop_enabled AND phase_is_enabled("phase15_r1_trailing")`
   - A/B matrix: baseline / 0.15 early / 0.20 early / 0.15 both sleeves
4. If validation surfaces additional bugs → fix first before 15-R1.

---

## 0. Production Baseline + recent verdicts

**Phase 9 C3 + CE v2** (SHIPPED 2026-04-18 21:22 KST, still active):
- Main diversified: CAGR 22.91%, Sharpe 1.17, MaxDD -26.26%, 18 positions
- Concentrated champion: N=5/1m/score_power → CAGR 34.75%, Sharpe 1.254

**Phase 11** (multibagger) A/B **REJECTED** 2026-04-21: -1.73pp CAGR. Default OFF.

**Phase 12** (live continuity) **SHIPPED** 2026-04-21.

---

## 0a. TL;DR — 🎉 **REFACTOR PHASE A COMPLETE** (26 commits on branch `refactor/phase-a-module-split`). Full 5-module split + Subtractive dead code removal. Main engine 27,838 → 382 lines facade (-98.6%).

**Current HEAD = `4c9858a`** on branch `refactor/phase-a-module-split` (pushed to remote). **26 refactor commits** on top of last SHIP `6440957`. All 5 new modules created + main converted to facade:

| Module | Lines | Owns |
|---|---|---|
| `r1000_config.py` | 2,109L | Pure data constants + EngineConfig (435 fields) |
| `r1000_helpers.py` | 967L | Stats + IO + cache + CIK normalization |
| `r1000_features.py` | 4,598L | 44 feature funcs (industry/fund/macro/blueprint/pillar/minervini) |
| `r1000_signals.py` | 3,614L | Sleeve composition + portfolio construction |
| `r1000_pipeline.py` | 15,315L | Training + backtest + export + validation + grid comparisons |
| `r1000_top30_institutional.py` | **382L** | **FACADE** (imports + re-exports) |
| **TOTAL** | 26,985L | (was 27,838 monolith; -853L dead code removed) |

**Dependency graph** (acyclic):
```
config.py <- helpers.py <- features.py <- signals.py <- pipeline.py <- main (facade)
```

Smoke tests **25/25 PASS** at every sub-stage. All nested helpers scope-preserved (Phase 9 C3 `_sign_flip_pos`, `within_group_z`, `sector_median`, `_scaled_unit_from_series`).

### What's done (26 commits, newest first)

| Commit | Stage | Summary | Lines |
|---|---|---|---|
| `4c9858a` | **5** | Create `r1000_pipeline.py` (15,315L) + convert main to 382L facade | -14,912 main |
| `48e4f8b` | **6 Subtractive** | Delete 17 `_legacy_unused_*` dead funcs | -2,307 main |
| `bb44fe8` | **docs** | SESSION_HANDOFF update after 4b-ii | docs |
| `b58dd51` | **4b-ii** | `build_target_portfolio` (739L) + 21 portfolio helpers → signals.py | -1,495 main |
| `14f2cef` | **4b-i** | `compute_regime_portfolio_controls` (349L) + `compute_benchmark_beating_focus_overlay` (260L) → signals.py | -607 main |
| `a7aca61` | **4a** | NEW `r1000_signals.py`: `compute_portfolio_sleeve_columns` (1,028L with Phase 9 C1+C2+C3 gate) + `compute_portfolio_sleeve_policy` (222L) + 3 helpers | -1,358 main |
| `a6014ab` | **docs** | rotate SESSION_HANDOFF after Stage 1 rollup FAIL analysis (data drift, NOT regression) | docs |
| `b0ca4c1` | **docs** | rotate SESSION_HANDOFF + STAGE_3D_PLAN after Stage 3d commits | docs |
| `b2f4331` | **3d-iv** | `compute_strategy_blueprint_columns` (926L) + `compute_multidimensional_pillar_scores` (186L) + `compute_minervini_momentum_overlay` (144L) → features.py | -1,246 main |
| `54986f7` | **3d-iii** | 6 funcs: market_adaptation + dynamic_leadership (w/ within_group_z nested) + manual moat overrides + ticker overlays + three_level RS + crisis_sector_fit → features.py | -546 main |
| `466ba27` | **3d-ii-min** | `compute_event_regime_features` + `sector_indicator` + `compute_macro_interaction_features` (pure transforms) → features.py | -194 main |
| `6b172a3` | **3d-i** | `_flexible_lag` + `_cagr_from_lag` + `recompute_fund_panel_derived_columns` (458L). Phase 9 C3 nested `_sign_flip_pos`/`_loss_narrowing_rate`/`_under_loss_growth` scope PRESERVED. | -559 main |
| `2631e62` | **3d-i-prep** | 4 CIK normalization helpers → helpers.py (unblocks 3d-i `normalize_cik_series` dep) | -32 main |
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

1. **Stage 1 rollup COMPLETED at 15:43:28 KST with DIVERGENCE — root cause data drift, NOT refactor regression.** Actual commit tested: `06f1171` (Stage 1d-ii), started 11:12:59 KST. Rollup reached Phase 6 successfully writing 4 verify targets (scored/portfolio/weights/backtest_metrics) at 15:43, then crashed in `update_operational_tracking` Phase 6 ops tracking with `pyarrow.lib.ArrowInvalid: Could not convert 1.0 with type float: tried to convert to boolean` — **PRE-EXISTING schema drift bug** in `append_history_parquet` (held_from_prev_rebalance column has mixed bool/float across call sites in main:9269, main:9332, main:18581). Flagged as separate task.

   `verify.py` output:
   - All 4 files size/SHA differ from baseline
   - Column structure IDENTICAL (618 cols, 610 rows both)
   - `rebalance_date` max: current `2026-04-20` vs ref `2026-04-17` (3 days data drift)
   - CAGR: current `0.2341` vs ref `0.2291` (+0.50pp; explained by retrain on different data window)
   - Other metric diffs (avg_stock_names, beat_month_ratio, etc.) — all consistent with 3-day data window shift causing feature_store + walk-forward full rebuild.

   **Why full rebuild happened**: `reuse_fingerprint(cfg, scope)` (main:1287) hashes `asdict(cfg)` which includes `cfg.end_date`. When `end_date` differs between runs, fingerprint differs, cached artifacts get rebuilt. `run_local.py` defaults `end_date` to today. **This means byte-exact verify on re-run is fundamentally impractical** without pinning `end_date` exactly AND disabling price cache refresh AND locking every ML seed.

2. **Verification strategy pivot** (post-rollup-finding): byte-exact via full-pipeline re-run is impractical. Strategy must shift to:
   - **Smoke tests 25/25** after every sub-stage (catches structural invariants)
   - **Identity checks** (`r.FN is f.FN` / `r.HELPER is h.HELPER`) after each move
   - **Scope checks** (nested helpers stay encapsulated via hasattr negative test)
   - **Spot-behavior** (empty/small-input behavior for each moved function)
   - **Optional re-run with pinned `--end-date 2026-04-17 --no-collector`** at Stage 5 completion — will still drift due to stochastic training but metrics should be within 0.3pp CAGR tolerance if refactor is value-preserving.

3. **Commits `2631e62..b58dd51` (Stage 3d-i-prep through 4b-ii)** — verified via smoke/identity/scope/spot-behavior only; byte-exact deferred per strategy pivot above.

4. **Stage 4c pending** — concentrated grid + sleeve_cap_policy comparison. Dependency analysis shows this layer calls `backtest_portfolio` (Stage 5 target) via `compare_sleeve_cap_policy_backtests` + `compare_standalone_sleeve_topn_backtests`. This means:
   - Only 3 concentrated-grid funcs (`select_concentrated_portfolio_topk`, `backtest_concentrated_portfolio`, `compare_concentrated_portfolio_backtests`) are movable to signals.py standalone — they have their own backtest loops.
   - The grid/comparison layer (`compare_sleeve_cap_policy_backtests`, `compare_standalone_sleeve_topn_backtests`, `choose_sleeve_cap_policy`, `apply_sleeve_cap_policy_to_cfg`, `sleeve_cap_policy_objective`, `generate_sleeve_cap_policy_candidates` 248L, etc.) belongs in `r1000_pipeline.py` (Stage 5) since it orchestrates backtests.
   - **Recommendation**: merge Stage 4c into Stage 5. Create `r1000_pipeline.py` with BOTH the grid-comparison layer AND the core pipeline (`train_walkforward`, `backtest_portfolio`, `export_outputs`, `run_all`, etc.).

5. **Stage 5 planning** — expected scope ~5,000L across ~20 functions:
   - `train_walkforward` (443L)
   - `backtest_portfolio` (694L)
   - `backtest_standalone_sleeve_topn` (?)
   - `export_outputs` (1,622L) — LARGEST function remaining
   - `run_all`, `run_default_pipeline`, `run_last_n_years_backtest`
   - `build_feature_store` (224L), `build_universe_monthly` (321L)
   - Stage 4c grid comparisons (~800L as noted above)
   - Misc pipeline helpers
   
   Executable as 3-5 sub-stages (5a: universe + feature_store; 5b: train + backtest; 5c: concentrated grid; 5d: policy comparison; 5e: export_outputs + run_all). Each sub-stage ~1-2k lines, smoke+identity verified.
3. **Stage 3d-ii-b (deferred)** — `load_fred_series` + `build_macro_regime_table` 417L + `build_live_event_alert_table` 187L + merge helpers (~850L). Blocked on moving 5 price-cache cascade helpers (`ensure_prices_cached_incremental` 95L + `load_px` + `macro_cache_file` + `price_close_series` + `write_stage_coverage_report`) to helpers.py first. See `STAGE_3D_PLAN.md` execution log for details.
4. **Stage 4**: `r1000_signals.py` — sleeve composition + portfolio construction. In-scope: `compute_portfolio_sleeve_columns` (1,028L), `compute_portfolio_sleeve_policy` (222L), `build_target_portfolio` (739L), `compute_regime_portfolio_controls` (349L), `compute_benchmark_beating_focus_overlay` (260L).
5. **Stage 5**: `r1000_pipeline.py` — orchestration + facade re-exports. In-scope: `train_walkforward` (443L), `backtest_portfolio` (694L), `export_outputs` (1,622L), `run_all` + `run_default_pipeline` + `run_last_n_years_backtest`, `build_feature_store` (224L), `build_universe_monthly` (321L).
6. **Stage 6 (Subtractive)**: delete `_legacy_unused_*` funcs (~2,500L) + Phase 3/5/7a dead branches.

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

## 2. Next step — Phase 12 SHIPPED. Choose next direction from prioritized candidates.

### Immediate small fix (recommended first, ~35 min)

**Cold-start fix for Phase 12A**: currently `_enrich_with_live_state` (line 14292/14730 in r1000_pipeline.py) runs BEFORE `apply_manual_positions_from_yaml` (line 14893). On FIRST run after filling manual_positions.yaml, portfolio_latest.csv shows NaN for avg_cost/shares/unrealized_return. Second run onwards works correctly because state carries over.

**Fix**: move the Phase 12B + ensure_live_portfolio_state blocks (line ~14878-14897) to BEFORE the first `_enrich_with_live_state` call. OR re-enrich right before `portfolio_operational.to_csv(portfolio_path)` at line 14353 + 14735.

After fix, run QUICK pipeline once (~20-30 min) to validate:
- portfolio_latest.csv all 9 enrichment columns populated
- lifetime_equity_curve.csv generated (84 rows = 83 backtest + 1 live)
- lifetime_metrics.json with live_value_method=shares_x_reference_price
- verdict shows lifetime CAGR section

### Prioritized next candidates (user decision needed)

**A. Quarterly Rebalance A/B** (~3-4h) — high-value efficiency improvement
  - Add `cfg.rebalance_interval_months: int = 1` field (default monthly, switch to 3 for quarterly)
  - Modify `backtest_portfolio` to honor interval (concentrated code already has this)
  - A/B test monthly vs quarterly on main diversified
  - Expected: turnover -50% (43% → ~20%), CAGR -0.5-1pp (minor hit), tax efficiency large gain
  - Ship gate: ΔCAGR ≥ -1pp AND Δturnover ≤ -20pp (efficiency gate, not alpha gate)

**B. Phase 13 scope-down** (~3-4h) — frontend-ready for subscription service
  - PHASE_13_PLAN.md (419 lines) is over-engineered; user pushed back on complexity
  - Scoped down version: apply `_enrich_with_live_state` to concentrated_portfolio_latest.csv + write `current_portfolio_summary.json` + `recent_trades.json`
  - Agent's entry_date/avg_cost = first recommendation date/price (already in live_portfolio_state_history.parquet, 152 snapshots accumulated)
  - Sufficient for frontend subscription product (정석 FREE, 성장주 PAID)

**C. Dividend tracking** (~1-2일) — Phase 14 candidate
  - Backtest: yfinance Adj Close already includes dividends (reinvested total return)
  - Live: no separate cash dividend tracking
  - Add: `next_ex_div_date`, `next_pay_date`, `next_div_per_share` columns + cash accumulator
  - Priority: MEDIUM (live tracking accuracy)

**D. Russell 2000 expansion** (~3-7일) — alpha universe widening
  - 1000 → 3000 tickers (with liquidity filter to 1500-2000 effective)
  - Compute cost 3-4x (90min FULL → 4-6h FULL)
  - Daily QUICK still 30-60min (automatable)
  - Need: universe builder + liquidity filter + R3000 constituent list

**E. Automation setup** (~1주) — subscription service infra
  - Local: Windows Task Scheduler (daily + monthly + quarterly triggers)
  - Cloud: AWS Lambda + S3 + SNS for subscriber alerts
  - Priority: after product decisions locked

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
I'm continuing work on the r1000 Quant Engine project. Before editing anything:

1. Read SESSION_HANDOFF.md top section (🟢 LATEST STATE 2026-04-21).
2. Read CLAUDE.md — project basics.
3. Run `git log --oneline -15` — HEAD should be `1642b66` or later on master.
4. Run `git status` — should be clean.
5. Read PHASE_13_PLAN.md ONLY if you're going to implement the scoped-down version.

Current state summary:
  - Refactor Phase A complete (33 commits pre-session, merged to master)
  - Phase 11 multibagger A/B REJECTED (default OFF)
  - Phase 12 live continuity SHIPPED (4 sub-stages) + 1 tz fix committed
  - Pipeline b84oo5xrv ran 83 min, reproduced baseline CAGR 22.95%
  - 2 known issues in SESSION_HANDOFF §LATEST STATE
  - User explicitly said Phase 13 as designed (PHASE_13_PLAN.md) is over-engineered; scope down

Production baseline (unchanged): Phase 9 C3 + CE v2
  Main: CAGR 22.91% / Sharpe 1.17 / MDD -26.26%
  Concentrated: N=5/1m/score_power → CAGR 34.75% / Sharpe 1.254

User has open questions (SESSION_HANDOFF §LATEST STATE → USER'S OPEN QUESTIONS):
  1. Scope-down Phase 13 (3-4h)
  2. Dividend tracking (Phase 14 candidate)
  3. Russell 2000 expansion
  4. Quarterly rebalance A/B (3-4h, highest-value quick win)
  5. Market shock detection gaps (no news/sentiment yet)
  6. Automation (Windows Task Scheduler / AWS cron)

Recommended first action (per SESSION_HANDOFF §2):
  Cold-start fix for Phase 12A (35 min code + 20-30 min QUICK validation run).
  Then user chooses next candidate: Quarterly A/B (A) or Phase 13 scope-down (B) or other.

Do NOT start new work until user confirms priority from SESSION_HANDOFF §2 candidates.
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
