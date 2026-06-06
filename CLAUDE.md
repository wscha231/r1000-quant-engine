# r1000 Quant Engine - Project Guide

## Project Overview
Russell 1000 기반 Top 30 기관급 퀀트 종목 선정 엔진. S&P 500 초과수익 목표.

## AlphaOps Data-First Contract
- Read `docs/ALPHAOPS_DATA_SYSTEM_CONTRACT.md` before changing AlphaOps vNext selection, sizing, cash, current-holding, or broker-replay policy.
- Do not interpret CAGR/MDD as production-valid unless `outputs/data_readiness/summary.json`, `outputs/reports/dataset_coverage_audit.json`, `outputs/sec_enriched_candidate_replay/summary.json`, `outputs/alphaops_vnext/summary.json`, and `outputs/portfolio_system_guard/error_check.json` all support the run.
- If SEC/Form4/13F/ETF/smart-money evidence exists, vNext production must use `outputs/sec_enriched_candidate_replay/candidate_replay_book_sec_enriched.csv`; summary-only evidence is not enough.
- Fix data restore, PIT availability, enriched-candidate materialization, and guard wiring before resuming CAGR/MDD optimization.
- Current official acceptance targets are broker-ledger next-close only: Main CAGR >= 35% and MDD no worse than -25%; Concentrated CAGR >= 50% and MDD no worse than -25%.
- Latest verified AlphaOps broker-ledger replay baseline is run `27056579679` on commit `b1f25d735f35d023504168258986a34d56dd2a10`: Main `35.9351%` CAGR / `-27.0180%` MDD; Concentrated `49.1663%` CAGR / `-23.5557%` MDD.
- If fullrun readiness is blocked by missing `data_raw/free/sec/companyfacts.zip`, refresh it through `free_data_lake_bootstrap.yml` or manual `free_data_daily_update.yml` with `sec_companyfacts=true` before trusting a new full rebuild.

## Key Files
- `SESSION_HANDOFF.md` — **다른 기기/세션에서 이어 작업할 때 제일 먼저 읽을 파일. "방금 뭐 했고 다음에 뭐 해야 하는지" 단일 inbox. Phase 하나 끝날 때마다 덮어씀.**
- `r1000_top30_institutional.py` — 메인 엔진 (~27,400+ lines, Phase 9 까지 shipped. C1+C2 verdict 확정 후 Refactor Phase A 로 5-module 분리 예정)
- `r1000_data_collector.py` — 데이터 수집 + 검증 파이프라인
- `colab_run.ipynb` — Colab 실행 런북 (GitHub master pull → collector → pipeline → validation). Cell 2 에 Phase 1-9 전체 env toggle. Cell 4 pipeline banner 에 `[commit=<sha>]` 표시 (`afaa768` 이후).
- `EXECUTION_PLAN.md` — **4-stage roadmap (Stage 0 = Phase 9 verdict 대기, Stage 2 = refactor+cleanup, Stage 3 = optional structural)**
- `ARCHITECTURE_REVIEW.md` — cold first-principles assessment + §6b sleeve taxonomy collapse 진단 + Phase 9 redesign 근거
- `REFACTOR_PLAN.md` — **27k→5 module 분리 + observability 인프라 + §12 5-stage 시퀀싱 다이어그램 (Verdict → C3 or Refactor → complement → Subtractive → Phase 8e). Phase 9 C1+C2 SHIP verdict 후 실행.**
- `PHASE_9_C3_PROPOSAL.md` — **Phase 9 C3 EPS turn-positive flag 상세 설계 (C1+C2 SHIP 후 구현 ready)**
- `PHASE_8_PROPOSAL.md` — Phase 8 restructuring (신규 8a/8b/8c/8d 설계 문서, shipped)
- `PHASE_ROADMAP.md` — **DEPRECATED** (Phase 1-6 만 커버, 7/8/9 없음). 현행 로드맵은 `REFACTOR_PLAN.md` §12 사용.
- `DIAGNOSIS_FACTOR_IC.md` / `DIAGNOSIS_COUNTERFACTUAL.md` / `DIAGNOSIS_BUGS.md` — Phase C 데이터 근거
- `PROPOSAL_defensive_upgrades.md` — Phase 6 (tail protection) 상세 설계 문서
- `PROPOSAL_growth_regime_offense_defense.md` — Phase 4 참고용 아키텍처 문서

## Current Engine Version
- `ENGINE_REUSE_VERSION = "2026-04-25-phase14-hybrid-alpha"` (in `r1000_config.py`)
- `ENGINE_COMMIT_SHA` (module-level, resolved at import from `git rev-parse --short HEAD`, printed in run banner per commit `afaa768`)
- Cache invalidation: 버전 문자열이 바뀌면 `cache_*`/`feature_store` 아티팩트가 자동 재생성됨.
- **Phase 14 (2026-04-25) wired validated Aggressive scanner alpha into 정석 ML cfg.features** — 6 columns added: rs_acceleration_score (T4 +10%), h1_oversold_value_score (Opus H1 +8.67%), h6_dynamic_leader_score (Opus H6 +7.38%), stage2_overext_penalty (T1 -2.5% protection), theme_phase_multiplier_{primary,max} (themes.yaml phase classifier). DEFAULT_FEATURES count: 232 → 238. **One FULL rebuild required** — see `PHASE14_VERDICT_PROCEDURE.md` for trigger + verdict procedure.

## Environments
- **Local**: `C:\Users\Andrew Cha\Documents\codex`
- **Colab**: `/content/drive/MyDrive/r1000_top30_institutional`
- **Python**: `py -3` (Windows에서 `python`/`python3`은 App Store redirect되므로 사용 금지)

## Known Issues
- Alpha Vantage 무료 키: 일일 25콜 제한, `alpha_vantage_free_tier_mode=True`

## Pipeline Execution Order (Colab)
1. `%pip install` dependencies
2. Drive mount + sys.path setup
3. `collector_lean_full_run_cfg()` → `run_data_collection(cfg)`
4. `run_default_pipeline(cfg)` → `run_full_validation_suite(cfg)`

## Config Presets
- `collector_full_run_cfg()` — 전체 신규 실행
- `collector_lean_full_run_cfg()` — comparison 생략한 경량 실행
- `collector_reuse_step2_cfg()` — 캐시 재사용 빠른 실행
- `pipeline_quick_rescore_cfg()` — **fast-iter용 preset (~15-25min). feature_store + 모델 재사용, scoring + backtest만 다시 실행. 시그널 공식 변경은 반영 안 됨 (캐시됨) — sleeve 가중치 / phase toggle 튜닝 전용.**

## Fast-Iteration Workflow
새 phase 실험할 때 매번 1.5-4시간 FULL rebuild 돌리지 말 것.

### Pre-commit smoke test (local, <10s)
```bash
py -3 tests/smoke_test.py                # 18 tests, ~7s full (syntax + structural + import + logic + regression)
py -3 tests/smoke_test.py --quick        # 10 tests, ~1s (syntax + structural only, no numpy import)
py -3 tests/smoke_test.py -v             # verbose — per-test PASS lines + timings
```

### Local pipeline run (no Colab round-trip)
```bash
py -3 run_local.py --verdict-only        # ~2s — just Cell E verdict on existing outputs (use after any run)
py -3 run_local.py                       # ~15-25 min — QUICK_RESCORE (default, sleeve/phase toggle tuning)
py -3 run_local.py --full                # ~2-3h CPU — FULL rebuild (required for feature_store schema changes)
py -3 run_local.py --no-collector        # skip collector step (use cached prices + SEC + macro)
py -3 run_local.py --phase9-c1=0         # A/B isolation: Phase 9 C1 OFF
py -3 run_local.py --phase9-c2=0         # A/B isolation: Phase 9 C2 OFF
```

Uses Drive mirror at `G:\내 드라이브\r1000_top30_institutional\` (override with `--base-dir`). Prints `[commit=<sha>]` banner (with `DIRTY` tag if working tree has uncommitted changes). Falls through to Cell E verdict at the end so you see SHIP/PARTIAL/REGRESS immediately.

**Why local**: eliminates `edit → commit → push → Colab pull → Cell 4` round-trip. Faster for A/B isolation (20min vs 40min for two Colab runs). No 12h Colab timeout. Direct file access.

**When to still use Colab**: (a) need GPU for FULL rebuild (CatBoost GPU), (b) no local Python/Drive sync, (c) shared team review. Colab notebook remains the canonical runbook.

Runs BEFORE `git push` → before Colab round-trip. Catches ~80% of bugs in 7 seconds instead of burning 20-180 minutes of Colab time on an obvious typo.

**What it covers** (see `tests/smoke_test.py` docstring):
- syntax: ast.parse + notebook JSON validity
- structural: PHASE*_COLUMNS in keep_cols (Phase 2 keepcols-fix regression), phase_is_enabled keys, ENGINE_REUSE_VERSION format, hard_sanitize dedup guard (d87160d regression), _sign_flip_pos semantics (Phase 9 C3 prereq), Phase 8+/9 dual-gate cfg fields
- import: engine module loads + key symbols exported (ENGINE_COMMIT_SHA, phase constants, weighted_sleeve_composite)
- logic: weight-0 skip regression, hard_sanitize overlap, phase_is_enabled env precedence, cross-sectional percentile semantics
- regression: PHASE1_ALPHA_COLUMNS complete, PHASE8B_LONG_LOOKBACK_COLUMNS complete, fund_panel carry_cols has sign-flip flags

**Adding a test when shipping a new phase**: open `tests/smoke_test.py`, copy a nearby @_test block, add assertion for your new behavior. Runtime budget: each test <500ms. Commit the test in the same commit as the feature.

### `colab_run.ipynb` cell 2 knobs
```python
QUICK_RESCORE_ONLY = True            # True=15-25min, False=FULL rebuild
PHASE1_ALPHA_ENABLED = 'auto'        # 'auto' | '0' | '1' (Phase 1 on/off)
PHASE2_INDUSTRY_ENABLED = 'auto'     # 'auto' | '0' | '1' (Phase 2 on/off)
```

### 모드 선택 규칙
| 변경 종류 | 모드 |
|---|---|
| sleeve 가중치 튜닝 | QUICK |
| phase A/B env toggle 측정 | QUICK |
| portfolio/cash cap 조정 | QUICK |
| 시그널 공식 변경 (`compute_*` / `build_*` / `add_*`) | FULL |
| `ENGINE_REUSE_VERSION` bump | FULL |
| walk-forward / embargo / 모델 구조 변경 | FULL |

### Phase toggle 매커니즘
- 엔진 최상단 `phase_is_enabled()` 헬퍼가 `PHASE_<KEY>_ENABLED` 환경변수 읽음.
- phase disable 시 관련 컬럼은 **삭제가 아니라 0.0으로 채움** (downstream sleeve 코드의 KeyError 방지).
- 새 phase 추가 시 반드시 같은 패턴 따를 것.

### 새 phase 추가 시 feature_store 생존 규칙 (2026-04-16 phase2-keepcols-fix)
`build_feature_store.keep_cols` 는 **명시적 whitelist** 다. `build_universe_monthly` 에서 붙인 컬럼이라도 whitelist 에 없으면 `fs = universe[keep_cols].copy()` 에서 drop 된다. 드롭되면:
1. `feature_store_latest.parquet` 에서 빠짐
2. walk-forward 가 훈련/스코어링할 때 `cross_sectional_robust_z` → NaN → 0.0 으로 fallback 돼서 시그널 contribution 이 **조용히 0 이 됨** (에러 없음)
3. `scored_latest.csv` 에도 안 나타남

**Phase 1 은 `compute_strategy_blueprint_columns` 가 `score_latest_month`/`prepare_latest_scored_data` 에서 재실행되므로 drop 돼도 최종 CSV 에는 나타난다** — 그래서 Phase 1 은 버그를 가려줬다. Phase 2 는 재계산 안 됐기 때문에 완전히 사라졌다.

**새 phase 추가 시 반드시**:
- `PHASE<N>_<NAME>_COLUMNS` 상수 만들고 (e.g. `PHASE2_INDUSTRY_COLUMNS`)
- `build_feature_store.keep_cols` 에 `+ PHASE<N>_<NAME>_COLUMNS` 추가
- 숫자 컬럼이면 같은 함수의 `hard_sanitize` 호출 리스트에도 추가
- phase toggle disabled 브랜치의 zero-placeholder 리스트와 동기화 유지

### A/B 측정 레시피
1. `PHASE_<KEY>_ENABLED=1` 로 QUICK run → metrics 기록.
2. `PHASE_<KEY>_ENABLED=0` 로 QUICK run → metrics 기록.
3. `outputs/concentrated_backtest_metrics.json`의 `strategy_cagr` / `sharpe` / `max_dd` diff.
4. phase ship 기준: Δ CAGR ≥ +0.5pp AND Δ MaxDD ≤ +2pp.

## Key Config Parameters
```python
cfg["reuse_existing_artifacts"] = True      # 캐시된 데이터 재사용
cfg["resume_partial_walkforward"] = False   # walk-forward 처음부터
cfg["macro_slow_release_lag_months"] = 1    # 매크로 지연 반영
cfg["companyfacts_refresh_days"] = 3        # SEC 데이터 갱신 주기
```

## Architecture
- Walk-forward training: 126일 embargo (look-ahead 방지)
- Ensemble: Ridge + LogisticRegression + CatBoost (reg/cls/rank)
- Point-in-time fundamentals: SEC accepted timestamp 기준
- Dual-sleeve portfolio: Core (70-95%) + Speculative (5-15%) + Cash (0-55%)
- Speculative hard stop-loss: -25%

## API Keys
- Alpha Vantage: 환경변수 `ALPHA_VANTAGE_API_KEY`
- SEC EDGAR: User-Agent 필요 (email)

## Changelog Writing Rules
- Write all CHANGELOG entries in **English only** — no Korean.
- Always include a real `HH:MM KST` timestamp. Never write `### KST -` without a time.
- Always include `symbols_added`, `symbols_changed`, `config_fields_added`, `breaking_changes` fields — use `none` when not applicable.
- List function/class names explicitly in `symbols_added`/`symbols_changed`, not prose descriptions.
- See the "Agent Update Contract" at the top of `CHANGELOG.md` for the full required format.

## Result Analysis
백테스트 결과에서 확인할 핵심 지표:
- `excess_cagr` > 0 → S&P 500 초과수익
- `ir` (Information Ratio) > 0.5 → 통계적 유의미
- `max_dd` — 최대 낙폭
- `beat_month_ratio` — 월간 승률
- `acceptance_checks` — 전체 통과 여부

## Phase 1+2 (2026-04-16) Alpha Columns to Check
새로 추가된 시그널 컬럼 (sanity check 용):
- Phase 1 (turnaround/value/uptrend):
  - `fundamental_turnaround_acceleration_score`, `cashflow_inflection_under_loss_score`
  - `value_inflection_score`
  - `uptrend_continuation_score`, `uptrend_breakdown_penalty`
- Phase 2 (industry RS / O'Neil leadership):
  - `industry`, `industry_group`, `subindustry` (from yfinance)
  - `rs_industry_{1,3,6,12}m`, `rs_industry_group_{1,3,6,12}m`
  - `industry_breadth_above_ma200`, `industry_group_breadth_above_ma200`
  - `industry_group_strength_score`, `industry_within_leader_rank`
  - `oneil_leadership_score`, `industry_rotation_signal`

## Current Production Baseline — Phase 15-D global_alpha_universe (SHIPPED 2026-04-29)
- **Main diversified: CAGR 24.51% / Sharpe 1.2453 / MaxDD -25.79% / IR 1.0244 / excess_cagr +11.02%**
- 18 current positions, avg_stock_names 24.33, beat_month_ratio 56.63%, turnover 48.5%
- Sleeve counts: core 6 / future 7 / early 4 (run d6bc807 verdict.log)
- Lifetime CAGR: **24.53% over 6.84y, +348.7%** (vs Phase 14 baseline +0.95pp)
- Top holdings: GOOG 12%, GEV 12%, NVDA 7.4%, TSM 7%, ASML 7%, ZTO 7%, CASH 5%, ADI 4.8%, MRVL 4.7%, LRCX 4.5%
- Universe: R1000 + 26 ADR + 5 cycle plays (BE/ALAB/ONTO/HIMX/INSM)
- Verdict: SHIP (dCAGR +0.93pp ≥ +0.5pp gate, dSharpe +0.067 ≥ -0.05, dMaxDD -2.62pp ≥ -3pp, early_scout=4 ≥ 4)
- Defined in `run_local.py` `CURRENT_BASELINE` dict (this section). Prior Phase 14 baseline preserved as `PHASE14_HYBRID_ALPHA_BASELINE` for historical delta calculations.

## Prior Production Baseline (archived) — Phase 14 hybrid alpha (SHIPPED 2026-04-27)
- Main diversified: CAGR 23.58% / Sharpe 1.1783 / MaxDD -23.17% / IR 0.9955 / excess_cagr +10.08%
- 19 positions, avg_stock_names 21.99, sleeve core 7 / future 7 / early 4 (run 24961673988)

## Phase 14 verdict note — ADR universe contribution still pending
- Phase 14 hybrid alpha SHIP verdict confirmed via GitHub Actions run 24961673988: CAGR +0.67pp, Sharpe +0.006, MaxDD +3.09pp better vs Phase 9 C3 + CE v2.
- New cfg.features (6): rs_acceleration_score, h1_oversold_value_score, h6_dynamic_leader_score, stage2_overext_penalty, theme_phase_multiplier_primary, theme_phase_multiplier_max.
- Critical caveat: `r1000+adr` did not actually exercise ADRs in that run (0/26 ADRs in `scored_latest.csv`; all rows came from `historical_membership_file`).
- Follow-up run 24974747494 proved ADR injection worked mechanically, but only 5 ADR/global-alpha rows reached `scored_latest.csv` and 0 were selected. ADR v2 expands the whitelist and adds `adr_global_alpha_fallback` for sparse foreign-issuer fundamentals; rerun full rebuild to measure contribution.
- Next open task: debug `.github/workflows/full_rebuild_manual.yml` input handling and `r1000_data_collector.py build_candidate_universe` before treating ADR alpha as tested.
- Artifacts are archived in `research/phase14_artifact/`.

## 🎯 Concentrated Champion — CAGR 30%+ goal achieved
- **N=5 / monthly rebalance / score_power weighting → CAGR 33.40% / Sharpe 1.284 / MaxDD -25.29%**
- Holdings (by score_power weight): MRVL 26.2%, AMKR 22.5%, WDC 18.7%, CIEN 18.3%, FTI 14.3%
- Prior Phase 9 C3 + CE v2 champion remains historical reference in `run_local.py PHASE9_C3_CE_V2_BASELINE`.
- Full grid/reference outputs live under Drive `outputs/` and archived Phase 14 artifacts under `research/phase14_artifact/`.

## Ship gate (for any next change)
- **ΔCAGR ≥ +0.5pp AND ΔSharpe ≥ -0.05 AND ΔMaxDD ≥ -3pp** (MaxDD positive delta = less drawdown = better)
- **Plus sleeve sanity**: early_scout count ≥ 4 (Phase 8 collapse regression guard)
- Check via `py -3 run_local.py --verdict-only` after any run.

## Historical baselines (reference only — do not use for verdict)
- Phase 9 C3 + CE v2 (prior production): CAGR 22.91%, Sharpe 1.1721, MaxDD -26.26%, IR 0.9474 — kept in `run_local.py PHASE9_C3_CE_V2_BASELINE`
- Phase 9 C1+C2 (prior): CAGR 21.69%, Sharpe 1.073, MaxDD -23.97%, IR 0.799 — kept in `run_local.py PHASE9_C1C2_BASELINE`
- Phase 8 pre-Phase-9: CAGR 21.86%, Sharpe 0.9856, MaxDD -32.08%, early_scout = 0 (sleeve collapsed)
- 2026-04-15 pre-Phase-1+2: CAGR 21.80%, Sharpe 0.73, MaxDD -36.86%, 2 names (extreme concentration)

## Multi-Session Phase Plan
**현행 로드맵 = `REFACTOR_PLAN.md` §12 5-stage 시퀀싱** (PHASE_ROADMAP.md 는 deprecated, Phase 1-6 만 커버).

**다른 기기/세션에서 이어 작업할 때 순서 (in order — don't skip)**:
1. **`SESSION_HANDOFF.md` 먼저** — "방금 뭐 했고 다음에 뭐 해야 하나" (single-item inbox, 가장 정확한 최신 상태).
2. 이 파일 (`CLAUDE.md`) — 프로젝트 베이직.
3. `CHANGELOG.md` 마지막 ~500줄 — 최근 결정 (Phase 8/9 entries).
4. `EXECUTION_PLAN.md` + `ARCHITECTURE_REVIEW.md` — 4-stage roadmap + ceiling assessment.
5. `REFACTOR_PLAN.md` §12 — 5-stage 시퀀싱 (Verdict → C3-or-Refactor → complement → Subtractive → Phase 8e).
6. `PHASE_9_C3_PROPOSAL.md` — Phase 9 C3 구현 시만 읽으면 됨 (~440 lines, 상세 snippets 포함).
7. `git log --oneline -10` — 최신 commit 확인. 기대 HEAD: `527fdde` 이상.
8. `outputs/backtest_metrics.json` + `outputs/concentrated_backtest_metrics.json` (on Drive) — 가장 최근 baseline.

**복붙용 부트스트랩 프롬프트는 `SESSION_HANDOFF.md` §4 에 있음.**

현재 상태 (2026-04-18 10:46 KST):
- Phase 1 ✅ SHIPPED (turnaround/value/uptrend alpha)
- Phase 2 ✅ SHIPPED (industry RS / O'Neil leadership)
- Phase 3 ❌ REJECTED (-2.30pp CAGR via A/B, default OFF)
- Phase 4 📋 PLANNED — regime-conditional dynamic sleeve weights (A/B pending)
- Phase 5 ❌ REJECTED (IC ≈ 0, default OFF)
- Phase 6a/6b ✅ SHIPPED (DD breaker + VIX guard, dormant in 83-month sample)
- Phase 6c 📋 OPT-IN — vol targeting (A/B pending)
- Phase 7a 📋 OPT-IN — insider flow + accruals quality (A/B pending)
- Phase 8a/8b/8c/8d ✅ SHIPPED — restructuring (CAGR 21.86%, PARTIAL verdict)
- **Phase 9 C1 ✅ SHIPPED code** — multi_year weight rebalance (`ced5db6`)
- **Phase 9 C2 ✅ SHIPPED code** — percentile thesis-gate (`ced5db6`)
- **Phase 9 C1+C2 verdict ⏳ PENDING** — FULL REBUILD started 2026-04-17 08:10 KST on `33581bc`, expected complete by now (2026-04-18 10:46); next agent runs Cell E verdict snippet from `SESSION_HANDOFF.md` §2.
- **Phase 9 C3 📋 DESIGNED** — EPS turn-positive flags (`PHASE_9_C3_PROPOSAL.md`), blocked on C1+C2 SHIP verdict.
- **Refactor Phase A 📋 PLANNED** — 5-module split + observability, after C1+C2 verdict + C3 decision.
