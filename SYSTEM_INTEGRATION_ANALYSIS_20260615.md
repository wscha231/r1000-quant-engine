# System Integration Analysis — 2026-06-15 KST

**Purpose**: Holistic audit of r1000-quant-engine — does it function as ONE integrated system that strengthens CAGR/MDD via data → selection → execution → defense → self-correction, or is it disconnected sidecars? Identifies every seam, ranks improvements, and proposes a code-search plan.

**Scope**: Snapshot at commit `cd480423` (P0a bull-floor shipped) + run `27516185696` A/B in progress (~102 min elapsed of ~3-4 h).

**Source**: 6 parallel Explore-agent audits + direct grep/Read on collector/sidecar/workflow files (~50 files inspected). Every claim has a file path + line number reference.

---

## 0. Current run state (snapshot)

- **Production ledger (cloud_results/performance_ledger/ledger.jsonl)** — 2 seed rows:
  - `27457206698` (a8b271ea, no T3): Main IS 22.14% / full 34.51%, Conc IS 21.65% / full 44.86%
  - `27498401423` (d42daf82, T3+conc-hyst, vNext): Main IS 21.45% / full 34.33%, Conc IS 21.29% / full 44.57%
  - **Trend**: REGRESSING (T3+conc-hyst was a wash on Main, slight regression on Conc)
  - **Recommended next focus**: `concentrated:structural_underinvestment_bull`
- **In-flight A/B (`27516185696`)**: `cd480423` + `PHASE_REGIME_CAPACITY_BULL_FLOOR_ENABLED=1` + vNext production. Tests whether bull-floor lifts Conc IS-CAGR above 21.29%. ETA ~80-120 min remaining.
- **Recently shipped this session**:
  - Tier-2 strengthened gates (`r1000_config.PORTFOLIO_GOAL_GATES`)
  - IS attribution sidecar (`tools/run_is_attribution.py`)
  - Performance ledger (`tools/run_performance_ledger.py`) — cumulative cross-run memory
  - Bull-floor in `apply_regime_capacity_overlay` (P0a)
  - Weekly cron on `full_rebuild_manual.yml` (heartbeat)

---

## 1. Subsystem map (audited, with file references)

### 1A. Data collection — partially automated, ADR/cycle manual

| Feed | Cadence | Source | Path | Auto? | Gap |
|------|---|---|---|---|---|
| **Prices (R1000)** | Daily 08:30 KST | yfinance/Alpaca/IWB live | `cache_prices/` | ✅ `free_data_daily_update.yml` cron `23 23 * * 1-5` | Manifest end-date validation missing (CLAUDE.md L12) |
| **Macro (FRED 14 series)** | Daily 08:30 KST | FRED API | `data_pit/macro/` | ✅ same workflow | Release-schedule unaware (static 1-month lag) |
| **SEC companyfacts** | Tue-Sat 09:15 KST | EDGAR bulk ZIP | `data_raw/free/sec/companyfacts.zip` | ✅ `data_readiness_preflight.yml` + 3-day threshold | Bulk ZIP is heavy (~1.3 GB) |
| **Form 4 (insider)** | Daily 08:20 KST, 20 tickers | EDGAR API | `data_pit/sec/shards/` | ✅ `sec_form4_daily_refresh.yml` | Universe bounded to 20 tickers (CLAUDE.md hint) |
| **13F (institutional)** | Quarterly Feb/May/Aug/Nov | EDGAR API | `data_pit/sec/13f_latest/` | ✅ `sec_13f_quarterly_refresh.yml` | Auto-manager selection static |
| **ETF holdings + N-PORT** | Monthly 1st day | iShares + SEC N-PORT | `data_pit/etf_holdings/` | ✅ `etf_holdings_monthly_refresh.yml` | iShares HTML parser fragile |
| **Post-disclosure** | Daily 09:45 KST | Form 4 + 13F signals | `outputs/post_disclosure_*` | ✅ `post_disclosure_alpha_pipeline.yml` | 180-day lookback static |
| **R1000 base universe** | On-demand | IWB live; static seed fallback | embedded in `r1000_pipeline.py:3672` | ✅ live → seed fallback | Seed file path implicit |
| **ADR whitelist** | **Manual** | **YAML curation** | `adr_universe.yaml` (77 tickers) | ❌ NO auto-refresh | mcap thresholds applied at filter time but no auto-flag |
| **Cycle plays whitelist** | **Manual** | **YAML curation** | `cycle_play_universe.yaml` (35 tickers) | ❌ NO auto-refresh | `last_refreshed` field exists but unused |
| **Data readiness orchestrator** | Tue-Sat 09:15 KST | preflight audit | `outputs/data_readiness/summary.json` | ✅ but **WARN-ONLY** (`full_rebuild_manual.yml:531`) | Does NOT block a rebuild even if coverage fails |

### 1B. Selection / leadership engine — NOT era-based as advertised

| Component | Where | What it does | Era-aware? |
|---|---|---|---|
| **Regime state classifier** | `r1000_features.py:5893-5932` | macro-only `bull/strong_bull/neutral/bear/deep_bear` from SPY/VIX/breadth | ❌ Coarse binary; can't tell 2020 software from 2024 AI |
| **Candidate lanes** (6) | `r1000_candidate_lanes.py:18-87` | QUALITY_COMPOUNDER / MARKET_LEADER / EMERGING_TENBAGGER / TOP7_MANAGER_DISCOVERY / CYCLICAL_RECOVERY / CRISIS_BENEFICIARY | ❌ Static feature composites; **never invoked in production scoring** — only research sidecar via `score_candidate_lanes` |
| **Theme phase classifier** | `r1000_themes.py:42-49, 321` | early/maturing/peaking/ending/dead → ±15% multipliers | ⚠️ Cross-sectional, not per-regime |
| **ML ensemble** | `r1000_pipeline.py:9744-9832` | Ridge + LogReg + CatBoost, blended 0.20/0.45/0.35 | ⚠️ **One global model**; regime adjusts BLEND weights post-hoc (`r1000_pipeline.py:9386-9505`), not coefficients |
| **Sizing** | `r1000_pipeline.py:14694-14719` | score-power (quadratic) + static caps `wmax=0.50` | ❌ Static, not regime-adaptive |
| **Monthly rebalance + exit** | `r1000_pipeline.py:11215-11847` | `position_risk_hard_stop=-0.08`, trailing -0.15 | ❌ No regime-conditional hold; no carry-over hysteresis in backtest |

**Verdict**: "시대별 주도 종목 선정"은 **마케팅용 그림** — 코드는 single global model + 사후 ensemble 재가중. 2020 software와 2024 AI는 같은 Ridge 계수로 평가됨.

### 1C. Crisis / defense sidecar — research-only daily, monthly rebalance-bound

| Component | Cadence | Touches production? |
|---|---|---|
| **Crisis signal builder** | per-run, in sidecars | ✅ Outputs `crisis_signals/daily_features.parquet` |
| **Long crisis dataset/learn/threshold** | per-run | ✅ but `production_activation_allowed=false` per Agent 4 |
| **Crisis state engine** | per-run + daily monitor | ✅ outputs `crisis_state` column on target book |
| **`apply_regime_capacity_overlay`** | per-month rebalance only | ✅ **the actual cash injector** — but driven by macro regime, not live crisis |
| **`apply_crisis_lane_policy`** | per-month | ⚠️ weight multipliers only, no guaranteed cash floor |
| **Daily crisis monitor** | daily 22:30 UTC | ❌ writes `research_only=True, auto_trade_allowed=False` |
| **Predictive MDD cash overlay** | per-run, research | ❌ `run_mdd_cash_overlay_research.py` artifact-only |
| **T4 reactive breaker** | parked | ❌ A/B'd as wash + slight loss |
| **Sub-daily / position-risk exits** | per-run, research | ❌ NOT in `broker_ledger_next_close` |

**Verdict**: 위기 감지 → 행동 사이 **0 to 30-day delay**. Daily monitor is advisory. 실제 cash 결정은 월 1회 rebalance 시 `regime_state` (macro)에 의존. CHANGELOG의 "regime_capacity dormant" 사건은 macro regime이 bull로 분류되어 multiplier=1.0이 되면 crisis state가 CRISIS_DEFENSE여도 cash가 안 오르기 때문.

### 1D. Self-improvement / auto-learning loop — mostly OPEN

| Chain | Status | Where it breaks |
|---|---|---|
| **Feature gates** quarterly_auto_learning → feature_gate_proposal → auto_feature_gates_candidate.yaml → human PR → research/auto_feature_gates.yaml → `r1000_features.py:6243 apply_phase18c_gates_to_frame` | ✅ **CLOSED** (one of two) | Human PR review intermediate step |
| **Layer-4 swap** `run_layer4_swap.py` → paper/live | ⚠️ Closed only when `execute=true` manually | Not auto on signal |
| **Winner lifecycle studies** | ❌ OPEN | diagnostic only, no auto-flip |
| **Monthly IC monitor** | ❌ OPEN | research publishing only |
| **Sleeve weight learning** | ❌ OPEN | candidate YAML written, no `r1000_main_v2.py` consumer |
| **Crisis threshold learning** | ❌ OPEN | learned thresholds emit `research_only=true`, never consumed at eval-time |
| **Performance ledger verdict** (just shipped) | ❌ OBSERVABILITY ONLY | REGRESSING detected but no auto-halt, no gate flip, no auto-experiment dispatch |

**`production_activation_allowed: false` is set in 174 files** (`r1000_main_v2.py:786`, `r1000_alpha_sprint.py:267`, `r1000_sidecar_promotion.py:454`, `r1000_concentrated_policy.py:428`, all `outputs/auto_learning/`, `outputs/main_v2/`, `outputs/orchestrator_replay/`). Per `research/multi_agent_operating_plan_20260516/agent_contracts.md:8`: "Research outputs must include `research_only=true` and `production_activation_allowed=false` where machine-readable metadata is written" — this is by design. The intended path is human-in-the-loop.

### 1E. Workflow orchestration & persistence

| Layer | Path | Durability | Note |
|---|---|---|---|
| **Drive / cloud_results** (git-committed) | `cloud_results/full_rebuild/<date>/` | per-run snapshot | rotated; performance_ledger is the only ACROSS-RUN accumulator |
| **GitHub artifacts** | various profiles | 30 / 365 days | ephemeral |
| **outputs/** (in repo) | local dir | per-run only | NOT committed (only artifacts + cloud_results) |
| **performance_ledger.jsonl** | `cloud_results/performance_ledger/ledger.jsonl` | **PERMANENT** (committed every run) | the only longitudinal memory |

**32 workflows, NO `workflow_run` or `repository_dispatch` triggers** — all independent cron or manual. Implicit chain via cached outputs.

**`data_readiness_preflight.yml` is warn-only** — never blocks a rebuild.
**`portfolio_system_guard` demotes hard-error runs to `failed_runs/` but doesn't fail the workflow.** The job succeeds, the outputs just don't overwrite canonical paths.

---

## 2. Integration verdict — IS it ONE system that strengthens CAGR/MDD?

**Answer: Partially. The PRODUCTION execution path is one wire, but four feedback loops are open and one ambition (era-based selection) doesn't exist in code.**

### 1F. CAGR/MDD attribution chain — 95% wired, 4 gaps

| Component | Where | Status |
|---|---|---|
| Final CAGR/MDD | `tools/run_account_evaluation.py:172,181-182` | ✅ VERIFIED |
| CAGR formula | `tools/run_broker_ledger_replay.py:451` | ✅ `(ending/starting)^(1/years) - 1` |
| MDD formula | `tools/run_broker_ledger_replay.py:452-453,485` | ✅ `min(equity/cummax - 1)` |
| Cost / fill lag | `tools/run_broker_ledger_replay.py:622,625` | ⚠️ **HARDCODED** (25 bps, 7-day) — not in `r1000_config.py` |
| IS/OOS split | `tools/run_broker_ledger_replay.py:500-501` | ⚠️ HARDCODED (`2024-07-01`, `2023-01-01`); env-var override mentioned in comments but **unread by code** |
| Target book | `tools/build_operating_target_books.py:94-107` → vNext replace | ✅ |
| vNext policy | `tools/run_alphaops_vnext_policy_replay.py:55-140` | ✅ (incl. P0a bull-floor) |
| Feature store keep_cols | `r1000_pipeline.py:8395-8474` + `r1000_config.py PHASE*_COLUMNS` | ⚠️ **FRAGILE whitelist** — new Phase columns silently drop if not added in two places. smoke_test catches if run, but no compile-time guard. |
| **Per-name CAGR 분해** | — | ❌ **TOOL MISSING** — can't decompose +7pp into per-name contribution |
| **MDD trough → 보유 종목 매핑** | trough_date reported but no automated snapshot link | ❌ MISSING |

### 2A. The CONFIRMED production wire (data → CAGR number)

```
Daily collectors (auto):
    free_data_daily_update.yml  ──►  cache_prices/, data_pit/macro/, data_raw/free/sec/
    sec_form4_daily_refresh.yml ──►  data_pit/sec/shards/
    etf_holdings_monthly_refresh.yml ──►  data_pit/etf_holdings/
    sec_13f_quarterly_refresh.yml ──►  data_pit/sec/13f_latest/
    post_disclosure_alpha_pipeline.yml ──►  outputs/post_disclosure_alpha_candidates/

Weekly Mon 09:00 UTC (new cron):
    full_rebuild_manual.yml triggers:
        run_local.py --full (collector + pipeline + walk-forward backtest)
            ──► outputs/scored_latest.csv (with `regime_state` as a feature)
            ──► outputs/feature_store_latest.parquet
        tools/run_full_rebuild_sidecars.py (operating_minimal):
            build_operating_target_books    ──► outputs/reports/operating_*_target_book.csv (RAW)
            build_long_crisis_inputs        ──► outputs/long_crisis_learning/  (research-only flag)
            build_sec_enriched_candidate_book ──► outputs/sec_enriched_candidate_replay/
                ─sec_form4 + sec_13f + etf_holdings + top7_manager_discovery joined─
            run_alphaops_vnext_policy_replay --production-output-mode replace_operating
                ──► OVERWRITES outputs/reports/operating_*_target_book.csv with vNext book
                    (applies regime_capacity overlay + crisis_lane_policy)
            run_broker_ledger_replay
                ──► outputs/broker_replay/<kind>/{metrics.json, equity_curve.csv, trades.csv}
            run_account_evaluation (Tier-1 + Tier-2)
                ──► outputs/account_evaluation/official_metrics.json
            run_is_attribution
                ──► outputs/is_attribution/{summary.json, <kind>_yearly.csv}
            run_performance_ledger
                ──► cloud_results/performance_ledger/ledger.jsonl (APPEND, COMMITTED)
        commit step:
            git add -f cloud_results/    (durable evidence)
            artifact upload (30-365d)    (ephemeral diagnostics)
```

This wire works. After my last 4 commits, every run produces:
- Tier-1 + Tier-2 verdict
- Per-year leak attribution
- One ledger row trended on IS-CAGR
- `dominant_open_leak` next focus

### 2B. The 7 BROKEN seams (where the loop is open, where ambition ≠ code)

1. **"Era-based leadership"는 코드에 없다** (Agent 2). Regime은 ensemble blend 가중치만 조정, 모델 계수는 모든 시대에 동일. 6개 lane은 production scoring을 안 함. → **2020 software와 2024 AI에 같은 `profitability_inflection_score` 가중치**.

2. **Crisis → action 지연 1-30일** (Agent 3). Daily monitor는 `research_only=True`. 실제 cash는 월 1회 rebalance 때 `regime_state` (macro)에 의존. `apply_regime_capacity_overlay`의 multiplier가 bull regime에서 1.0이면 crisis_state가 CRISIS_DEFENSE여도 cash가 안 올라감 ("dormant" 사건).

3. **Auto-learning promotion이 5/7 open-loop** (Agent 4). 학습 결과가 174개 `production_activation_allowed: false` 깃발에서 막힘. 새 ledger는 REGRESSING을 감지하지만 **자동 행동 없음** — 사람이 읽고 dispatch 해야 함.

4. **Data readiness가 warn-only** (Agent 5). ETF 0%, 13F missing, smart_money missing이어도 rebuild 진행. 침묵하는 dead-feed 위험 (SESSION_HANDOFF.md 2026-06-09 'data-hole program' 정확히 이 문제).

5. **ADR + cycle plays whitelist 수동 큐레이션** (Agent 1). 새 leadership이 등장해도 사람이 yaml에 손으로 추가해야. 자동 후보 발굴 없음.

6. **Sidecar outputs는 git-commit 안 됨**, GitHub artifact (30-365d)만. cross-run 분석을 위해 archive를 뒤져야 함. performance_ledger만 영구.

7. **SEC evidence가 production에 닿는 분기점이 미묘** — `portfolio_policy=alphaops_vnext_production`일 때만. `production_baseline`이 default였던 시절 cash overlay 붕괴 사건의 root cause (CHANGELOG 2026-06-14 21:30 KST). 내가 default를 alphaops_vnext_production로 바꿔 고쳤지만, 외부 자동화 사용자는 여전히 input footgun 가능.

8. **CAGR/MDD attribution 도구가 95% 까지만 분해됨** (Agent 6). per-name CAGR 분해 도구가 없어 bull-floor가 7pp 올려도 어디서 왔는지 (NVDA? ASML? 2021 cash 전개? 2023 cash 전개?) 알 수 없음. MDD trough → 보유 종목 매핑도 없음.

9. **하드코딩된 핵심 파라미터** — `cost_bps=25`, `max_fill_lag_days=7`, `oos_start='2024-07-01'`이 `r1000_config.py`에 없고 `tools/run_broker_ledger_replay.py` 안에 박혀있음. env-var override는 comment에 언급되지만 실제 코드는 안 읽음.

10. **keep_cols whitelist fragility** — 새 Phase 컬럼이 `PHASE*_COLUMNS` 상수와 `build_feature_store.keep_cols` 둘 다에 안 들어가면 침묵 드롭. smoke_test 가드는 있지만 컴파일-타임 체크 없음. Phase 2가 이걸로 1주 동안 0이었던 사건 (CLAUDE.md L118-130).

### 2C. 결론

- **데이터 수집**: 6/8 자동, ADR/cycle 수동 (수정 가능, 작은 일).
- **선택 엔진**: regime-aware blending은 작동하지만 **era별 모델은 없음** (큰 구조적 갭).
- **매수매도**: 월 rebalance + 정적 stop이 production, sub-daily는 research-only (보유 기간 52일이 이걸 반영).
- **위기 감지**: 시그널은 있지만 **시그널-행동 wire 끊김** (1-30일 지연).
- **자가수정**: 7/7 중 2개만 closed-loop, ledger는 observability-only.
- **통합**: 다섯 표면이 같은 production wire를 통과하지만, **3개 표면에서 시그널이 production scoring에 닿지 못함** (era model, daily crisis, learned thresholds).

**한 줄 진단**: 정직한 평가 인프라(Tier-2 + IS attribution + ledger)는 방금 갖춰졌고 첫 fix(bull-floor)가 측정 중. 하지만 **"era-based leadership"과 "daily crisis 방어"는 슬로건일 뿐 코드가 아니어서**, IS-CAGR 21% 한계는 fix 한 두 개로 35/50% 도달 불가능. **두 큰 구조 변경 (per-regime sub-model + daily crisis → daily action wire)** 없이는 CLAUDE.md 목표(35/50)는 OOS lottery 기반 환상.

---

## 3. 우선순위 개선 계획 (priority matrix)

| Prio | Item | 예상 효과 | 비용 | Why first |
|---|---|---|---|---|
| **P0** | **Bull-floor A/B 결과 reading + 승격 결정** | conc IS +5-10pp 가능 | 0 (run 끝나면) | 이미 진행 중 |
| **P0a** | **Daily crisis → broker action wire** | MDD -3 to -8pp 가능 | 중 (1주) | 위기 감지가 작동해도 1-30일 지연 = 무용지물 |
| **P0b** | **Per-regime sub-model** (bull-only / bear-only Ridge/LR/CatBoost) | IS-CAGR +3-8pp 가능 | 대 (2-3주) | era별 leader가 다르므로 single global 계수가 천장 |
| **P1** | **Ledger → auto-halt / auto-A/B dispatch** | 사람 개입 없이 루프 닫힘 | 소 (3-5일) | 자가수정 키스톤. 지금은 observability만 |
| **P1** | **`production_activation_allowed` 자동 승격 게이트** (Tier-2 strengthened_pass + 2회 연속 IMPROVING이면 자동 promote) | open-loop 5개 중 3개 자동화 | 중 (1주) | 학습 결과가 production에 안 닿는 174-flag 문제 해결 |
| **P1** | **Data readiness를 hard-fail로** (ETF coverage_etf_ratio ≥ 0.30 등 SESSION_HANDOFF에서 약속한 lockdown 실행) | dead-feed 회귀 차단 | 소 (1-2일) | warn-only는 침묵 위험 |
| **P2** | **ADR/cycle plays auto-candidate** (분기 1회 yfinance mcap+volume 스캔 → 후보 PR 자동 생성) | 신규 leadership 캐치 | 중 (1주) | 큰 효과는 아니지만 누락 방지 |
| **P2** | **Sub-daily exit 또는 PRWV를 production books에 wire** | MDD 추가 -2pp | 중 (1주) | T4는 wash였으나 selective trailing은 다를 수 있음 |
| **P2** | **outputs/ 핵심 산출물 git commit** (sidecar metrics, target_books) cross-run 분석 가능하게 | dev 속도 | 소 (반일) | 지금은 archive 뒤져야 함 |
| **P3** | **macro release-calendar awareness** (M2/CPI 실제 발표일 기반 lag) | IC 약간 개선 | 소 (반일) | 작은 alpha |
| **P2** | **per-position CAGR/MDD attribution tool** (`tools/run_per_position_cagr_attribution.py`) | 진단 (직접 alpha는 아님) | 중 (3-5일) | 무슨 lever가 작동했는지 알아야 다음 lever 선택. 지금은 ledger가 "+7pp가 어디서 왔는지" 못 답함 |
| **P2** | **MDD trough → 보유 종목 매핑** (broker_replay에 trough-date holdings snapshot 추가) | 진단 | 소 (1-2일) | "왜 2023-08-17 트로프?" 자동 답 |
| **P2** | **cost_bps + oos_start를 `r1000_config.py`로 끌어올리기** | configurability | 소 (반일) | A/B/sensitivity 안 막힘 |
| **P2** | **keep_cols whitelist 컴파일-타임 가드** (`assert all(c in keep_cols for PHASE in PHASE*_COLUMNS for c in PHASE)`) | 회귀 방지 | 소 (반일) | Phase 2 사건 재발 방지 |

**먼저 P0a + P0b + P1 ledger-loop 3개를 1-2 주에 끝내면 35/50% target 도달 가능성이 처음으로 의미 있어집니다.** P0, P0a, P0b는 IS-CAGR 갭 14pp의 직접 출처.

---

## 4. 코드서치 계획 (concrete next-step roadmap)

다음 세션이 그대로 실행할 수 있는 순서:

### Step 1 — P0 bull-floor verdict reading (A/B 완료 직후)
- `git fetch && git pull` → 새 bot commit 확인
- `cat cloud_results/performance_ledger/ledger_summary.md` → 3행 trend 확인
- `cat cloud_results/full_rebuild/20260615_global_alpha_universe/is_attribution/concentrated_summary.md` → 2021/2023이 healthy로 바뀌었는지 확인
- 의사결정: 합격(IS-CAGR↑, MDD≤-25%) → `tools/run_alphaops_vnext_policy_replay.py:2718` 의 `phase_is_enabled("regime_capacity_bull_floor")` default를 True로 flip + smoke 갱신 + 다음 run에서 확정 측정

### Step 2 — P0a Daily crisis → broker action wire (Code search)
- `Grep "research_only.*True\b"` on `tools/run_daily_crisis_monitor.py` → 어느 flag를 풀어야 production에 닿는지 확인
- `Read tools/run_alphaops_vnext_policy_replay.py:2550-2700` → `apply_crisis_lane_policy`가 어디서 daily crisis_state를 읽는지 (현재 월별 lookup), daily 갱신 hook 가능 위치
- `Grep "rebalance_date\|next_close_fill"` on `tools/run_broker_ledger_replay.py` → mid-month forced rebalance 주입 가능한 entry point
- **Design**: crisis_state가 GREEN→CRISIS_DEFENSE 천이 시 그날 EOD에 보유 weight를 cash로 30-50% 옮기는 "crisis override row"를 target book에 inject. broker_replay가 그 행을 발견하면 T+1에 fill.
- 새 sidecar `tools/run_crisis_override_injector.py` 작성 → `daily_crisis_states.csv` 읽고 `operating_*_target_book.csv`에 override row append.

### Step 3 — P0b Per-regime sub-model (가장 큰 작업, but 가장 큰 lever)
- `Read r1000_pipeline.py:9386-9505` (`compute_regime_ensemble_weights_adaptive`) — 현재 regime-by-blend 로직.
- `Grep "walk_forward\|fit_models\|train_models"` on `r1000_pipeline.py` → 훈련 루프 위치.
- **Design 후보 2개**:
  - (a) 라이트: regime-stratified `sample_weight`을 ensemble 훈련에 추가. 한 모델, 시대 가중치 다름.
  - (b) 헤비: regime별 별도 Ridge+CatBoost. 각 시대의 회복기/끝물기 데이터로 학습.
- A/B 가능한 env toggle: `PHASE_PER_REGIME_SUBMODEL_ENABLED`.
- 예상 작업: r1000_pipeline.py ~500줄 신규 함수 + DEFAULT_FEATURES 영향 분석 + smoke + FULL rebuild A/B.

### Step 4 — P1 Ledger → auto-action loop closure
- `Read tools/run_performance_ledger.py` → `compute_verdict`에 다음 행동 결정 추가.
- 새 sidecar `tools/run_ledger_action_router.py`:
  - Read `latest_verdict.json`
  - If `state == REGRESSING` 2 runs in a row → 자동 revert: 마지막 env override를 0으로 되돌리고 다음 A/B를 dispatch (gh API)
  - If `state == IMPROVING` AND `strengthened_pass=true` for 2 runs → 자동 promote: 해당 env toggle을 cfg field로 confirm + revert 어려운 cfg 변경은 PR 자동 생성
- `.github/workflows/ledger_action_router.yml` 새 워크플로 (full_rebuild 완료 후 trigger via workflow_run)
- `Grep "workflow_run:" .github/workflows/` → trigger 패턴 참고

### Step 5 — P1 production_activation gate 자동화
- `Grep "production_activation_allowed" --include='*.py'` → 174 사이트 카테고리 분류
- 가장 영향력 있는 chain (auto_learning_policy_candidate, auto_feature_gates 외) 우선
- `tools/auto_policy_promote.py:93` 의 promotion rule에 `strengthened_pass + 2-run streak` 조건 추가
- 새 unit test: 가짜 ledger로 자동 승격 트리거 검증

### Step 6 — P1 Data readiness lockdown
- `Read .github/workflows/full_rebuild_manual.yml:531-535` (warn-only 라인)
- `data_coverage_gate.py --no-fail` → `--no-fail`만 빼면 hard-fail 모드
- SESSION_HANDOFF.md 2026-06-09 lockdown plan 따르기: `coverage_etf_ratio ≥ 0.30`, `coverage_top_manager_ratio ≥ 0.05` 두 floor를 enforce
- 첫 hard-fail 발생 시 어떤 feed인지에 따라 자동 retry 또는 human alert.

### Step 7 — P2 ADR/cycle plays auto-candidate
- 새 sidecar `tools/run_universe_candidate_scanner.py`:
  - 분기 1회 yfinance로 mcap > $5B + 90-day liquidity > $50M USD/day 종목 스캔
  - `adr_universe.yaml`, `cycle_play_universe.yaml`과 diff → 후보 출력
  - 자동 PR 생성 (`mcp__github__create_pull_request`)으로 사람 review
- workflow: monthly cron, manual dispatch.

### Step 8 — P2 sub-daily / PRWV production wire
- `Read tools/run_position_risk_weekly_validation.py` — 현재 어느 stop이 가장 efficient한지
- T4 reactive wash 교훈: hard stop 단독은 wash. **Selective trailing** (높은 conviction은 더 느슨, 약한 conviction은 더 타이트) A/B 해봄직.
- env-gated, ledger로 측정.

### Step 9 — per-position CAGR 분해 도구 (P2)
- 새 `tools/run_per_position_cagr_attribution.py`:
  - `broker_replay/<kind>/account_state_daily.csv` (있으면) 또는 `trades.csv` + `equity_curve.csv` 합성
  - 각 종목 × 각 month: `per_name_return = (price_end / price_start - 1) × weight_avg`
  - 전체 CAGR을 `sum(per_name_contribution) + cash_drag + cost_drag`로 분해
  - 두 run 비교 모드: `--baseline run_X --variant run_Y` → 차이 분해 (각 lever의 진짜 기여도)
- sidecar 통합: `tools/run_full_rebuild_sidecars.py`에 추가, ledger row에 top-3 contributor 노출

### Step 10 — MDD trough → holdings snapshot (P2)
- `tools/run_broker_ledger_replay.py:485` 트로프 보고 다음에 그 날 holdings + per-name P&L 14일 직전부터 저장
- 새 column in metrics.json: `max_dd_trough_top_offenders` (top 3 names + their per-name DD contribution)

### Step 11 — outputs/ 핵심 산출물 git commit
- `full_rebuild_manual.yml` commit step에 `outputs/account_evaluation/`, `outputs/is_attribution/`, `outputs/broker_replay/{kind}/metrics.json` 추가
- repo size 영향 작음 (메트릭 JSON 수 KB)

---

## 5. 다음 세션이 즉시 해야 할 일 (TL;DR)

1. A/B (`27516185696`) 완료 알림 받으면 `cloud_results/performance_ledger/ledger_summary.md` 확인 → 새 ledger 3행으로 bull-floor verdict 자동 출력
2. 합격 시 **bull-floor default ON** flip (Step 1 위)
3. **Step 2 (daily crisis wire)와 Step 4 (ledger auto-action)를 병렬로 시작** — 둘 다 5일 내 ship 가능, 둘 다 큰 영향. Step 3 (per-regime sub-model)은 이 두 개가 안정된 후.

---

## 6. 핵심 발견 요약 (one-line each)

- ✅ **데이터 수집 자동화**: 8 feeds 중 6 auto, 2 (ADR, cycle plays) 수동.
- ❌ **시대별 주도 종목 선정**: 코드에 없음, regime은 blend 가중치만 조정.
- ⚠️ **매수매도 (수익률 극대화)**: 월 rebalance + 정적 stop이 production. sub-daily는 research-only.
- ⚠️ **위기 감지**: 시그널 builder 작동, 행동까지 1-30일 지연.
- ⚠️ **자가수정 개선**: 7 chain 중 2 closed, 5 open. ledger는 observability만.
- ⚠️ **통합·연결되어 ONE CAGR/MDD 결과**: 같은 production wire를 통과하지만, 3개 시그널이 실제 scoring에 못 닿음. IS-CAGR 21% 한계는 우연이 아닌 **구조**.

End of analysis — `cd480423` snapshot, 2026-06-15 KST.
