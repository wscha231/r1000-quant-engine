# Codex Goal-Setting Brief — r1000-quant-engine

> **이 문서는 Codex가 r1000-quant-engine의 다음 분기/스프린트 목표를 제안할 때 따라야 하는 brief입니다.**
> User가 Codex에게 "다음 목표 짜줘"라고 했을 때 Codex는 §0~§8를 모두 따라 출력해야 합니다.
> Claude Code (in-CLI executor)와 ChatGPT Pro (strategy/review)는 이 문서를 참조용으로 읽되, 직접 따르지 않습니다.

---

## 0. 권한 한계 (가장 먼저 읽을 것)

### 0.1 Codex가 결정할 수 있는 것

| 레벨 | 결정권 | 예시 |
|---|---|---|
| **Operational** (per-A/B, per-run) | ✅ FULL | "이번 A/B는 bull-floor 0.85 vs 0.80 비교" |
| **Tactical** (per-week, per-sprint) | ✅ FULL with §6 format | "이번 주 P0.2 crisis wire 구현 + 8년 bootstrap 병행" |
| **Strategic** (per-quarter, 6-12개월) | ⚠️ 제안만 → ChatGPT Pro 리뷰 필수 → user 승인 | "Q3 내 IS-CAGR 21→30% 달성" |
| **Mission** (전체 프로젝트 north star) | ❌ NEVER 재정의 | Main 35% / Conc 50% / MDD -25%는 CLAUDE.md 픽스됨 |

### 0.2 Codex가 절대 할 수 없는 것

1. **`CLAUDE.md`의 official targets (35/50/-25/-25) 재정의** — 사용자만 가능.
2. **`PORTFOLIO_GOAL_TARGETS` (`r1000_config.py:517`)** 또는 `PORTFOLIO_GOAL_GATES` 변경 — 코드 PR로만 가능, 직접 goal 문서에서 재정의 불가.
3. **OOS-inflated headline CAGR을 목표로 삼기** — Finding F4 위반. 반드시 IS-CAGR로 anchoring.
4. **검증 불가능한 정성 목표** ("엔진을 더 robust하게") — 모든 목표는 §3 KPI에 매핑.
5. **시한 없는 목표** — 모두 시한 + fallback 명시.

### 0.3 Codex 작성 시 의무 절차

1. §1 데이터를 **직접 fetch** 해서 확인 (claims만 따라하지 말 것).
2. §6 출력 형식 **정확히** 따를 것 (YAML 권장; 자유형식 금지).
3. 작성 후 `docs/proposals/goals_<YYYYMMDD>.yaml`로 commit 후 PR.
4. PR title 형식: `proposal(goals): <sprint or quarter> targets — <one-line summary>`.
5. ChatGPT Pro review 요청을 PR description에 명시.
6. 절대 master에 push 금지. 별도 branch `codex/goals-<YYYYMMDD>` 사용.

---

## 1. Codex가 먼저 fetch해 확인해야 할 데이터

목표를 제안하기 전에 **반드시 다음 7개 소스를 직접 읽고** 인용하세요. "들었다"가 아니라 "현재 값이 X이다"로 작성.

### 1.1 누적 트렌드 — performance ledger
```bash
cat cloud_results/performance_ledger/ledger.jsonl | python3 -c "
import sys, json
rows = [json.loads(l) for l in sys.stdin if l.strip()]
for r in rows[-5:]:
    for k in ('main', 'concentrated'):
        p = r['portfolios'][k]
        print(f\"  {r['run_id'][:11]} {k:13} IS={p.get('is_cagr',0)*100:.2f}% full={p.get('full_cagr',0)*100:.2f}% MDD={p.get('max_dd',0)*100:.2f}% pass={p.get('strengthened_pass',False)}\")
"
```
→ IS-CAGR이 최근 N runs 동안 IMPROVING / FLAT / REGRESSING 어느 쪽?

### 1.2 현재 official metric
```bash
cat cloud_results/full_rebuild/latest_global_alpha_universe/account_evaluation/official_metrics.json | python3 -c "
import sys, json
d = json.load(sys.stdin)
for k, p in d['portfolios'].items():
    print(f\"  {k:13} Tier-1 CAGR={p['cagr']*100:.2f}% (target {p['cagr_target']*100:.0f}%), MDD={p['max_dd']*100:.2f}% (target {p['max_dd_target']*100:.0f}%), pass={p['target_pass']}, strengthened={p.get('strengthened_pass',False)}\")
"
```

### 1.3 어디서 새고 있는지 — IS attribution
```bash
cat cloud_results/full_rebuild/latest_global_alpha_universe/is_attribution/concentrated_summary.md
cat cloud_results/full_rebuild/latest_global_alpha_universe/is_attribution/main_summary.md
```
→ 어느 연도가 `structural_underinvestment_bull` / `flat_alpha_invested` / `over_defense_bear_ok` 태그?

### 1.4 데이터 가용성 — 8년 readiness
```bash
ls outputs/eight_year_readiness/ 2>/dev/null
cat outputs/data_readiness/summary.json 2>/dev/null | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('  status:', d.get('status'), '| blockers:', d.get('blockers',[])[:5])
"
```
→ 필요 시작일 2018-06-12 대비 현재 시작일은? 417 tickers 중 PIT-safe하게 보유한 비율은?

### 1.5 시스템 통합 진단
```bash
head -100 SYSTEM_INTEGRATION_ANALYSIS_20260615.md
```
→ F1~F6 발견 중 아직 미해소된 것은?

### 1.6 contract + mission
```bash
head -80 docs/ALPHAOPS_DATA_SYSTEM_CONTRACT.md
grep -A2 "Current official acceptance targets" CLAUDE.md
```

### 1.7 진행 중인 작업 — handoff
```bash
sed -n '/## 0. ACTIVE INBOX/,/## 1. CRITICAL/p' SESSION_HANDOFF_20260615.md
sed -n '/P0.1 — Read bull-floor/,/P0.2/p' SESSION_HANDOFF_20260615.md
```

**이 7개 데이터를 인용하지 않은 goal 제안은 reject 대상입니다.**

---

## 2. 목표 계층 구조 (Hierarchy)

모든 목표는 4개 레벨로 매핑되어야 합니다.

```
MISSION (CLAUDE.md, 픽스)
    └─ Main 35% CAGR / -25% MDD AND Conc 50% / -25% on broker_ledger_next_close, ≥8y window
        │
        ├─ STRATEGIC (분기, Codex 제안 → ChatGPT Pro review → user 승인)
        │   └─ 예: "Q3 2026 내 IS-CAGR 두 책 모두 30% 도달"
        │       │
        │       ├─ TACTICAL (스프린트/주, Codex 자유 결정)
        │       │   └─ 예: "주 3에 P0.2 crisis wire ship + 8y bootstrap 완료"
        │       │       │
        │       │       ├─ OPERATIONAL (A/B/run, Codex 자유 결정)
        │       │       │   └─ 예: "A/B 27600000: bull-floor 0.85 vs 0.80 비교"
```

각 레벨은 **반드시 위 레벨에 연결**되고 **아래 레벨로 분해**되어야 합니다. 고립된 goal 금지.

---

## 3. 측정 가능한 KPI 프레임워크

모든 goal은 다음 5개 KPI 카테고리 중 **최소 2개**에 매핑돼야 합니다.

### 3.1 Performance (정직한 지표 — F4 준수)

| KPI | 출처 | Pass 기준 (예시) |
|---|---|---|
| **IS-CAGR** (PRIMARY) | `account_evaluation.is_cagr` | Main ≥ 25%, Conc ≥ 30% |
| OOS/IS ratio | Tier-2 gate | ≤ 3.0x |
| Sharpe (full window) | `broker_replay.sharpe` | Main ≥ 1.20, Conc ≥ 1.40 |
| Recent 3y MDD | `windows.oos2.max_dd` | ≥ -25% |
| Full CAGR | `broker_replay.cagr` | reference only (NEVER as primary target) |

**❌ NEVER 사용**: full-period CAGR 단독, OOS-only CAGR.

### 3.2 Data integrity

| KPI | 출처 | Pass 기준 |
|---|---|---|
| Broker replay window 길이 | `metrics.json.years` | ≥ 8.0 |
| Cache 시작 날짜 | `cache_prices/manifest.json.start` | ≤ 2018-06-12 |
| Target book coverage | `coverage_gate.json.coverage_*` | etf ≥ 0.30, top_manager ≥ 0.05 |
| SEC companyfacts 신선도 | `data_readiness.summary.companyfacts_age_days` | ≤ 5 |
| Hard error count | `portfolio_system_guard.error_check.json` | = 0 |

### 3.3 Loop closure (자가수정 진척도)

| KPI | 출처 | Pass 기준 |
|---|---|---|
| `production_activation_allowed: true` 비율 | grep count | category (b) 50% → 80% |
| Ledger auto-action 발화 횟수 | `ledger_action_router/log` | week당 ≥ 1 |
| Closed-loop chain 수 | audit count | 현재 2 → 4 |

### 3.4 Defense responsiveness

| KPI | 출처 | Pass 기준 |
|---|---|---|
| Crisis signal → action 최대 지연 | `crisis_override_injector/log` | ≤ 2 trading days |
| MDD trough magnitude | broker_replay | recent ≤ -25% |
| Cash deploy/redeploy 주기 | `cash_policy_attribution` | 분석 가능해야 |

### 3.5 Process discipline

| KPI | 출처 | Pass 기준 |
|---|---|---|
| Smoke coverage 비율 | `tools/run_pr_validation.py` | 신규 도구 100% |
| Tier-2 strengthened_pass true ratio (last 5 runs) | ledger | ≥ 60% |
| Failed run ratio (`failed_runs/` 이동) | bot commits | ≤ 20% |

---

## 4. 정직 원칙 (Honesty Anchors)

### 4.1 Null hypothesis 명시

모든 goal에 **"실패 판정 조건"**을 명시. 예:
- ✅ "Bull-floor가 conc IS-CAGR 21.29% → 26%+로 lift. Null: IS-CAGR < 23% 또는 MDD < -28%면 reject"
- ❌ "Conc 성과 개선" (실패 판정 불가)

### 4.2 Lottery 회피

- 단일 A/B의 +Npp 결과 단독으로 mission 달성 선언 금지.
- "OOS 1.95년에서 +Npp 났다" → Mission 달성 아님. **IS 동시 개선 필수**.

### 4.3 Multi-test correction

- 한 스프린트에 N개 A/B을 dispatch하면, 단일 통과 기준을 약간 strict (예: 0.5pp 추가 margin).
- 이유: false positive rate 누적.

### 4.4 Baseline drift 추적

- "이전 baseline 대비 +Npp" 주장 시, 두 run의 commit SHA + 시작/종료 날짜 + universe mode 동일 확인.
- 다르면 "drift 가능성 있음 — 추가 control run 필요" 표시.

### 4.5 Honest failure mode 표기

모든 goal에 다음 표기:
- **확률적**: "70% 확률로 달성 예상" (근거 명시)
- **결정론적**: "데이터만 들어오면 100% 달성" (예: 8y bootstrap)
- **탐색적**: "달성 여부 불확실, 실험 가치 있음" — KPI 통과보다 학습 가치 우선

---

## 5. Goal 시간 단위 + Cadence

| 레벨 | 주기 | 작성 시점 | 검토 시점 |
|---|---|---|---|
| Operational | per A/B / per run | 매 A/B dispatch 전 | A/B 완료 24h 내 |
| Tactical | weekly | 월요일 09:00 KST | 다음 월요일 |
| Strategic | quarterly | 분기 시작 1주 전 | 분기 중간 + 분기 종료 |
| Mission | annually | CLAUDE.md 갱신 시 | 분기마다 reaffirm |

**Strategic 이상은 사용자 승인 필수.** Tactical은 PR 머지로 채택. Operational은 dispatcher 자동 실행 가능.

---

## 6. 출력 형식 (의무)

YAML로 작성. JSON도 허용. Markdown 자유형식 **금지**.

### 6.1 파일 경로

`docs/proposals/goals_<YYYYMMDD>.yaml`

### 6.2 필수 스키마

```yaml
metadata:
  proposer: codex
  proposed_at: 2026-06-15T10:30:00Z
  reviewer_required: chatgpt_pro
  user_approval_required: true  # strategic 이상이면 true
  source_data_checked:
    - cloud_results/performance_ledger/ledger.jsonl  # commit SHA: <sha>
    - cloud_results/full_rebuild/latest_global_alpha_universe/account_evaluation/official_metrics.json  # SHA
    - SYSTEM_INTEGRATION_ANALYSIS_20260615.md  # last_modified
    - SESSION_HANDOFF_20260615.md
    - docs/ALPHAOPS_DATA_SYSTEM_CONTRACT.md
    - CLAUDE.md
  current_state:
    main_is_cagr: 0.2145  # actual value, not assumed
    conc_is_cagr: 0.2129
    main_mdd: -0.2593
    conc_mdd: -0.2588
    broker_window_years: 7.03
    ledger_trend: REGRESSING  # IMPROVING | FLAT | REGRESSING | FIRST_RUN
    dominant_open_leak: concentrated:structural_underinvestment_bull
    open_loop_chains: 5  # of 7

mission:
  source: CLAUDE.md
  immutable: true
  targets:
    main:  { cagr: 0.35, max_dd: -0.25 }
    concentrated: { cagr: 0.50, max_dd: -0.25 }
  metric_mode: broker_ledger_next_close
  window_years_required: 8.0

strategic_goals:
  - id: SG-2026Q3-01
    title: Close the IS-CAGR honesty gap
    horizon: 2026-Q3 (2026-07-01 to 2026-09-30)
    contributes_to: mission.targets
    success_kpis:
      - kpi: main_is_cagr
        baseline: 0.2145
        target: 0.28
        source: account_evaluation.portfolios.main.is_cagr
      - kpi: conc_is_cagr
        baseline: 0.2129
        target: 0.32
        source: account_evaluation.portfolios.concentrated.is_cagr
      - kpi: oos_is_ratio_main
        baseline: 3.53
        target_max: 2.5
        source: tier2_gates.oos_is_cagr_ratio_max
    failure_criteria:
      - "main_is_cagr < 0.24 at quarter end"
      - "ledger trend REGRESSING for ≥3 consecutive runs"
    probability_estimate: 0.55  # codex's honest estimate with reasoning
    probability_reasoning: |
      Bull-floor A/B baseline shows ~5pp Conc lift is plausible if 2021/2023 leak
      tags clear. Per-regime sub-model could add additional 3-5pp if data sparsity
      manageable. 8y bootstrap adds 1 IS year (2018-06 to 2019-06), worth ~1-2pp.
      Total budget: ~9-12pp upside, target 7pp Main / 11pp Conc → tight but feasible.
    dependencies:
      - 8y data bootstrap completion
      - bull-floor A/B verdict (P0.1)
      - per-regime sub-model design review (P0.3)
    decomposes_into: [TG-WK24-01, TG-WK25-01, TG-WK26-01]

tactical_goals:
  - id: TG-WK24-01
    title: P0.1 bull-floor verdict + promotion decision
    horizon: 2026-W24 (2026-06-15 to 2026-06-21)
    contributes_to: SG-2026Q3-01
    parent_dependencies: []
    success_kpis:
      - kpi: ledger_row_count
        baseline: 2
        target: 3
        source: cloud_results/performance_ledger/ledger.jsonl
      - kpi: a_b_verdict_published
        target: true
        source: CHANGELOG.md
      - kpi: conc_is_cagr_delta_from_seed_2
        baseline: 0
        target_min: 0.03  # +3pp vs run 27498401423
        source: ledger.portfolios.concentrated.is_cagr - 0.2129
    failure_criteria:
      - "Bull-floor A/B fails (conc IS-CAGR < 0.23) and no fallback A/B dispatched within week"
    probability_estimate: 0.95  # mostly mechanical
    operational_breakdown:
      - id: OG-AB27516
        action: Read run 27516185696 verdict from ledger
        owner: claude_code
        deadline: 2026-06-15T18:00 KST
      - id: OG-AB-NEXT
        action: |
          IF pass: flip bull-floor default ON + commit + smoke + push
          IF fail: dispatch follow-up A/B with floor=0.80 (relaxed)
        owner: claude_code
        deadline: 2026-06-16T12:00 KST

  - id: TG-WK24-02
    title: 8-year data bootstrap unblock
    horizon: 2026-W24
    contributes_to: SG-2026Q3-01
    parent_dependencies: []  # parallel with TG-WK24-01
    success_kpis:
      - kpi: broker_window_years
        baseline: 7.03
        target: 8.0
        source: broker_replay.metrics.json.years
      - kpi: cache_start_date
        baseline: 2019-05-31
        target: 2018-06-12
        source: cache_prices/manifest.json.start
    failure_criteria:
      - "PIT universe label coverage < 80% for 2018 names"
      - "yfinance backfill failure rate > 10%"
    probability_estimate: 0.85
    blockers_resolved_by_this_goal:
      - price cache window
      - target book window
      - PIT universe label
    operational_breakdown:
      - id: OG-BOOTSTRAP-RUN
        action: Dispatch bootstrap_free_data_for_8y_window workflow
        owner: user_or_dispatcher
        deadline: 2026-06-16

operational_goals:
  # Inherited from tactical_goals[].operational_breakdown
  # Codex can add additional per-A/B targets here
  - id: OG-AB-DESIGN-CRISIS-WIRE
    action: ChatGPT Pro design crisis_override_injector.md
    owner: chatgpt_pro
    deadline: 2026-06-17

risk_register:
  - risk_id: R-1
    description: "8y data shortage forces strategic goal extension"
    likelihood: medium
    impact: high
    mitigation: "Prepare 7y fallback acceptance criteria; do not block other tactical work"
  - risk_id: R-2
    description: "Per-regime sub-model overfits deep_bear (1 year of data)"
    likelihood: high
    impact: medium
    mitigation: "ChatGPT Pro to design regularization spec before Claude implements; fall back to regime-weighted single model"
  - risk_id: R-3
    description: "production_activation_allowed audit reveals signal that breaks broker_ledger gate"
    likelihood: low
    impact: very_high
    mitigation: "ALL flips gated by Tier-2 strengthened_pass + 2-run streak; auto-revert on first regression"

anti_goals:
  # Things Codex commits to NOT pursue this period
  - "Chasing full-period CAGR > 35/50 if IS-CAGR < 25/30 (F4 violation)"
  - "Adding new lane to candidate_lanes.py without per-regime evaluation (perpetuates F1)"
  - "Adding new feature without registering in PHASE_*_COLUMNS + keep_cols (silent-drop)"
  - "Setting any production_activation_allowed=true outside the P1.2 gate"
  - "Dispatching A/B without portfolio_policy=alphaops_vnext_production (F5)"

acceptance_protocol:
  who_reviews:
    strategic_goals: chatgpt_pro -> user
    tactical_goals: chatgpt_pro (advisory)
    operational_goals: none (dispatcher auto)
  review_sla_hours: 48
  rejection_handling: |
    On rejection, Codex rewrites with the reviewer's feedback within 24h.
    Maximum 2 rewrite rounds; 3rd round escalates to user direct discussion.
  promotion_rule: |
    Tactical goal "Achieved" requires KPI pass AND ledger row evidence committed.
    Strategic goal "Achieved" requires all tactical children Achieved AND 2-run streak.
```

### 6.3 검증 가능성

PR description에 다음을 포함:
- 각 KPI의 `source` field가 실제 파일 경로 + JSON path로 valid한가?
- `current_state` 값이 §1 명령으로 reproducible한가?
- 각 `failure_criteria`가 자동 검출 가능한가? (ledger row 또는 CI gate)

---

## 7. 좋은 vs 나쁜 Goal 예시

### 7.1 좋은 Operational goal
```yaml
id: OG-AB-BULL-FLOOR-RELAX
action: |
  Dispatch full_rebuild_manual.yml with:
    PHASE_REGIME_CAPACITY_BULL_FLOOR_ENABLED=1
    bull_floor=0.80 (relaxed from default 0.85)
    portfolio_policy=alphaops_vnext_production
success_kpi: conc_is_cagr >= 0.25 in ledger row
failure: conc_is_cagr < 0.23 OR conc_mdd < -0.28
fallback_on_failure: revert default OFF; document in CHANGELOG
deadline: 2026-06-17
owner: claude_code
```

### 7.2 나쁜 Operational goal
```yaml
id: OG-IMPROVE-CONC
action: Make concentrated better
success_kpi: better CAGR
# ❌ 측정 불가, source 없음, failure 미정, fallback 없음
```

### 7.3 좋은 Tactical goal
```yaml
id: TG-WK24-DAILY-CRISIS
title: P0.2 daily-crisis broker action wire ship
horizon: 2026-W24
success_kpis:
  - kpi: max_crisis_to_action_lag_trading_days
    source: outputs/crisis_override_injector/log
    target_max: 2
  - kpi: tests_run_per_pr_validation
    baseline: 32
    target_min: 40  # +8 new smoke tests for crisis wire
failure_criteria:
  - "Tests pass but ledger row count < +1 by 2026-06-21"
deadline: 2026-06-21
```

### 7.4 나쁜 Tactical goal
```yaml
id: TG-CRISIS-FIX
title: Fix crisis sidecar
# ❌ horizon 없음, KPI 없음, 어느 strategic에 연결되는지 없음
```

---

## 8. 다음 호출 시 Codex가 받을 prompt 예시

User가 Codex에 다음과 같이 요청:

> "r1000-quant-engine 다음 분기 목표 짜줘. SESSION_HANDOFF + SYSTEM_INTEGRATION_ANALYSIS 읽고. Codex Goal-Setting Brief 따라서."

Codex 응답 형식:
1. §1의 7개 데이터 fetch 결과를 **먼저 인용** (값과 출처).
2. `docs/proposals/goals_<YYYYMMDD>.yaml` 한 파일로 §6.2 스키마 채워서 출력.
3. PR title + body 제안.
4. ChatGPT Pro에 보낼 review request 1단락 (강조할 위험 요소).
5. user 확인 요청 문항 (≤3개).

---

## 9. 절대 금지 (요약)

- ❌ Mission 재정의
- ❌ OOS-inflated headline을 primary target으로
- ❌ 측정 불가능한 정성 목표
- ❌ 시한 없는 목표
- ❌ failure criteria 없는 목표
- ❌ source field 없는 KPI
- ❌ 단일 A/B 결과로 strategic 달성 선언
- ❌ master에 직접 push
- ❌ §1 데이터 확인 없이 추정값으로 작성
- ❌ §6 스키마 무시한 자유형식

---

## 10. Brief 변경 절차

이 brief 자체의 수정은:
- Codex가 직접 수정 불가.
- ChatGPT Pro가 개선안 제안 → user 승인 → Claude Code가 commit.
- 변경 시 모든 진행 중 goal의 `metadata.brief_version`을 새 버전으로 업데이트.

---

**End of Codex Goal-Setting Brief — 2026-06-15 KST, v1.0**

Maintainer: Claude Code (이 문서 commit).
Reviewer: ChatGPT Pro (분기마다 적절성 재검토).
Authority over content: user.
