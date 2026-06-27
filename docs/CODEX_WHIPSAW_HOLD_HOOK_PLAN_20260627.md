# Codex Implementation Plan — Whipsaw Audit + Earnings-Confirmed Hold Hook

> 목적: 진단된 1차 실패(whipsaw — 강한 주도주를 너무 빨리 팔고 비싸게 재매수)를
> 측정·보완하는 두 작업을 무오류로 구현. 목표는 Concentrated CAGR ≥ 50%, MDD ≥ -25%.
> 출처: `docs/CODEX_GOAL_SETTING_BRIEF.md`, 사용자 2026-06-27 정성 진단.
> 작성 2026-06-27. measurement-only + default-OFF 원칙 엄수.

---

## 🟦 [PASTE TO CODEX FROM HERE] 🟦

## 0. Objective + Non-Negotiables

```
Goal (fixed):  Concentrated CAGR >= 50%, MDD >= -25%  (broker_ledger_next_close)

Diagnosis (user, 2026-06-27, validated):
  The engine picks good leaders (SNDK/WDC/CIEN/LITE/BE are DUAL_LEADER with
  strong 1m/3m/6m RS vs SPY/QQQ). The dominant failure is NOT selection — it
  is holding/turnover timing: it trims/sells strong leaders on a short
  volatility shake, then re-buys them higher next rebalance.

  Trade-log evidence (Concentrated, 2026 Apr->May):
    WDC : sold ~$297 -> rebought ~$431  (+45% rebuy)
    SNDK: sold ~$692 -> rebought ~$1187 (+71% rebuy)
    LITE: sold ~$764 -> rebought ~$949  (+24% rebuy)
    CIEN: sold ~$415 -> rebought ~$535  (+29% rebuy)
  Premature-sell audit recurring names: TSLA, PENN, PLTR, LITE, MU, WDC.

  Broad "hold everything longer" was already REJECTED (you'd hold losers too).
  Surviving candidate: hold-extension gated on actual_results_score > 0
  (fundamentally confirmed leaders only).

Non-negotiables:
  - No live trading.
  - No production mutation. No target/cash/sizing policy change on default path.
  - No proxy 8Y/10Y work. No partial-year annualized 2026 proof.
  - No promotion claim until pit_universe_label_clean=true AND broker-ledger
    evidence passes the contract.
  - forward 126d is an AUDIT LABEL only, never a live ranking signal.
  - One task = one branch = one PR. No safety/gate/require-X proliferation.
  - Report FULL-period broker delta as primary. OOS is reference only.
```

Location discipline: every command tagged `[LOCAL]` / `[GITHUB]` / `[DRIVE]`.

---

## 1. Two-part plan (measure the prize, then build the lever)

```
W-AUDIT (PR 1): Whipsaw cost audit — quantify how much CAGR premature sells cost.
                Measurement-only. This sets the CEILING on what the hold hook
                can recover. If whipsaw cost is tiny, the hook is not worth a
                broker A/B.

HOLD-HOOK (PR 2): Earnings-confirmed hold-extension hook — default OFF.
                Protect fundamentally-confirmed leaders from score-dip trims;
                sell only on thesis-break. The actual lever.
```

순서: **W-AUDIT 먼저.** whipsaw 비용 숫자가 의미 있어야(예: full-period ≥ +3pp CAGR 회수 잠재) HOLD-HOOK broker A/B가 정당화됨. W-AUDIT 결과가 작으면(<1pp) HOLD-HOOK 보류하고 사용자 보고.

---

## 2. PR 1 — Whipsaw Cost Audit (W-AUDIT)

### 2.1 Branch
`codex/whipsaw-cost-audit-20260627`

### 2.2 File 신규
`tools/run_whipsaw_cost_audit.py`

### 2.3 입력
- `outputs/broker_replay/<kind>/trades.csv` (이미 존재 — ticker, side, fill_price, quantity, date, signal_date)
- `outputs/broker_replay/<kind>/equity_curve.csv` (가중치 환산용, 선택)
- cache_prices (sell 후 보유했으면 얼마였을지 counterfactual용)

### 2.4 정의 — 무엇을 측정하나

```
Whipsaw event = 같은 ticker를 SELL(또는 부분 trim)한 뒤 N개월 이내 더 높은 가격에
                다시 BUY(또는 비중 확대)한 사례.

per event:
  sell_date, sell_price, sold_weight_or_qty
  rebuy_date, rebuy_price, rebuy_weight_or_qty
  rebuy_premium = rebuy_price / sell_price - 1     (양수면 비싸게 재매수)
  gap_days = rebuy_date - sell_date
  # 그 사이 보유했으면 놓친 수익(또는 피한 손실):
  held_through_return = price_at_rebuy_date / sell_price - 1   (= rebuy_premium과 동일 근사)

per ticker aggregate + portfolio aggregate:
  whipsaw_event_count
  median_rebuy_premium
  positive_premium_share          # 비싸게 재매수한 비율
  # 추정 비용: sold_weight * rebuy_premium 의 합 → CAGR 환산
  estimated_drag_pp_full          # full-period 추정 CAGR drag
  estimated_drag_pp_oos           # OOS 구간 (참고)
```

### 2.5 핵심 산출 — "회수 가능 상한"

```
recoverable_ceiling_full_pp = sum over whipsaw events of
    (sold_weight * rebuy_premium), annualized over full-period years

이게 HOLD-HOOK이 회수할 수 있는 최대치의 보수적 추정.
실제 회수는 이보다 작음 (모든 sell이 잘못된 건 아니므로).
```

### 2.6 Output schema
`outputs/whipsaw_cost_audit/<kind>_summary.json`:
```json
{
  "schema_version": "whipsaw-cost-audit-v1",
  "portfolio": "concentrated",
  "metric_mode": "broker_ledger_next_close",
  "lookback_months_for_rebuy": 3,
  "whipsaw_event_count": 0,
  "median_rebuy_premium": 0.0,
  "positive_premium_share": 0.0,
  "estimated_drag_pp_full": 0.0,
  "estimated_drag_pp_oos": 0.0,
  "recoverable_ceiling_full_pp": 0.0,
  "top_events": [
    {"ticker": "SNDK", "sell_date": "2026-04-01", "sell_price": 692.0,
     "rebuy_date": "2026-05-01", "rebuy_price": 1187.0, "rebuy_premium": 0.715,
     "sold_weight": 0.30, "gap_days": 30}
  ],
  "verdict": "whipsaw_drag_material" | "whipsaw_drag_minor" | "insufficient_events"
}
```

verdict threshold:
- `estimated_drag_pp_full >= 3.0` → `whipsaw_drag_material` (HOLD-HOOK 정당화)
- `>= 1.0` → `whipsaw_drag_minor` (선택적)
- `< 1.0` or events < 5 → `insufficient_events` (HOLD-HOOK 보류)

`report.md`도 생성 (top_events 표 + verdict).

### 2.7 Smoke `tests/whipsaw_cost_audit_smoke.py` (7 test)
1. 합성 trades: SELL@100 → BUY@140 within 30d → 1 event, rebuy_premium 0.40
2. SELL@100 → BUY@90 (싸게 재매수) → positive_premium_share 0
3. SELL 후 재매수 없음 → event 0
4. SELL 후 4개월 뒤 재매수 (lookback 3개월 초과) → event 0
5. estimated_drag_pp 계산 정확 (known weight × premium)
6. verdict threshold (3.0 / 1.0)
7. empty trades → insufficient_events

### 2.8 Wire
`tools/run_full_rebuild_sidecars.py`의 `run_performance_ledger.py` 다음:
```bash
  python tools/run_whipsaw_cost_audit.py --latest-run outputs --output-dir outputs/whipsaw_cost_audit 2>&1 | tee outputs/full_rebuild_logs/whipsaw_cost_audit.log || true
```

### 2.9 검증 명령
```bash
[LOCAL] python3 tests/whipsaw_cost_audit_smoke.py
[LOCAL] python3 tools/run_pr_validation.py --only whipsaw_cost_audit
[LOCAL] python3 tools/run_whipsaw_cost_audit.py --latest-run <clean_7y_artifact>/outputs --output-dir /tmp/wc
[LOCAL] cat /tmp/wc/concentrated_summary.json   # 실제 drag 숫자 확인
```

### 2.10 Est: 2일. PR 본 작업: tools + smoke + 1줄 wire + PR validation 등록 = 4 파일.

---

## 3. PR 2 — Earnings-Confirmed Hold-Extension Hook (HOLD-HOOK)

**W-AUDIT verdict가 `whipsaw_drag_material`일 때만 진행.** 아니면 사용자 보고.

### 3.1 Branch
`codex/earnings-confirmed-hold-hook-20260627`

### 3.2 핵심 설계 — 기존 기계 재사용 + 펀더멘털 게이트

기존에 이미 hold-bonus / hysteresis 기계가 있다 (`compute_conviction_hold_bonus` / concentrated hysteresis / T3 sigma-gate). **새로 만들지 말고 그걸 gate해서 재사용.**

핵심 차이: broad hysteresis는 wash였다. **이번엔 `actual_results_score > 0` + thesis-intact 로 gate** → 펀더멘털 확인된 리더만 보호. 이게 survive한 이유.

### 3.3 Hook 동작 (default OFF, env `PHASE_EARNINGS_CONFIRMED_HOLD_ENABLED`)

```
대상: Concentrated 현재 보유 종목 (held_from_prev_rebalance=true)

보호 조건 (ALL true면 hold-protect):
  pit_leader_hold_candidate == true
  actual_results_score > 0                    # 실적/가이던스 확인
  thesis_intact == true, where thesis_intact =
      rs_benchmark_3m > 0                      # 3m RS 유지
      AND price_above_ma200 == 1               # MA200 위
      AND NOT guidance_deterioration           # 가이던스 악화 아님
                                               # (eps_revision_score >= 0 근사)

보호 동작:
  보유 종목이 그 달 score-rank 하락으로 trim/drop 대상이 되어도,
  보호 조건 충족 시 hold (또는 hold-bonus로 rank 유지) → score-dip 매도 차단.

매도 조건 (thesis-break — 이것만 매도 허용):
  rs_benchmark_3m <= 0 (3m RS 붕괴)
  OR price_above_ma200 == 0 (MA200 이탈)
  OR actual_results_score <= 0 또는 eps_revision_score < 0 (실적/가이던스 악화)
  OR 섹터 리더십 약화 (industry_group_strength_score 하위)
  → thesis-break이면 보호 해제, 정상 매도.

비보호 종목 (actual_results_score <= 0 또는 thesis 깨짐): 기존 로직 그대로.
```

### 3.4 Cap 처리 — cap-safe vs uncapped 분리 (필수)

보유 보호는 winner 비중을 키울 수 있음 (안 팔면 자라남). SNDK 36.7% 같은 cap 초과 위험.

**두 모드 모두 측정:**
- `cap_safe`: 보호 후 단일 종목 30% cap 재적용 (water-fill 재clamp, 기존 `capped_proportional_fill` 재사용)
- `uncapped`: cap 미적용 (telemetry로 초과 노출)

env `R1000_HOLD_HOOK_CAP_MODE=cap_safe|uncapped` (default cap_safe).

### 3.5 Telemetry (행 단위)
```
earnings_confirmed_hold_protected (bool)
earnings_confirmed_hold_reason ("actual_results+thesis_intact" | "not_confirmed" | "thesis_break")
pre_hold_hook_weight
hold_hook_weight_delta
hold_hook_cap_mode ("cap_safe"|"uncapped")
hold_hook_cap_exceeded (bool)
hold_hook_single_max_weight (관측 최대 단일 비중)
```
summary 레벨: `applied_count` (보호 발화 행 수), `protected_tickers`, `thesis_break_sells`.

### 3.6 Code touched (최소)
- `tools/run_alphaops_vnext_policy_replay.py` — hold-protect 분기 (Concentrated, final caps 이후, 행 emit 이전)
- `tests/alphaops_vnext_policy_replay_smoke.py` — 보호 발화 / thesis-break 매도 / cap-safe vs uncapped / default OFF 테스트 추가

selection/scoring/cash 엔진 (`r1000_pipeline.py`, `r1000_features.py`, `r1000_signals.py`, `r1000_candidate_lanes.py`) 수정 **금지**.

### 3.7 Smoke (alphaops_vnext_policy_replay_smoke.py에 추가, 6 test)
1. default OFF → 보유 보호 0, 기존 동작 byte-identical
2. ON + actual_results_score>0 + thesis_intact → 보호됨 (score-dip에도 hold)
3. ON + actual_results_score<=0 → 보호 안 됨
4. ON + thesis_break (3m RS<0) → 보호 해제, 매도 허용
5. cap_safe 모드 → 단일 종목 ≤ 30%
6. uncapped 모드 → 초과 허용 + cap_exceeded telemetry true

### 3.8 검증 후 — cheap broker A/B (별도, fullrun 아님)

PR 2 머지 후, 사용자 승인 하에:
```
baseline (hook OFF) vs hook ON(cap_safe) vs hook ON(uncapped)
  → 기존 clean 7Y operating_concentrated_target_book.csv 에 hook 적용
  → tools/run_broker_ledger_replay.py (next_close, 25bps) 3개 모두
  → full-period CAGR/MDD delta 비교 (OOS는 참고만)
```
이 cheap harness는 W-AUDIT/HOLD-HOOK과 별개 작업 (PR 3 후보). 지금은 설계만.

### 3.9 Est: 3일.

---

## 4. Acceptance (broker A/B 시, 미리 합의)

```
HOLD-HOOK 성공 기준 (broker_ledger_next_close, full-period):
  Concentrated CAGR full delta:  meaningful + toward +3.76pp gap
  Concentrated MDD:              must NOT worsen beyond -25.82% (gate -25%)
  OOS:                           must not collapse (참고, primary 아님)
  applied_count > 0:             hook이 실제 발화했는지 (0이면 무의미)

cap_safe가 cap_exceeded 효과 없이 엣지를 보이면 우선 채택.
uncapped가 더 좋아도 MDD 악화면 reject (cap-breach가 MDD 위험).
```

---

## 5. Anti-Proliferation + Branch Whitelist

```
허용 브랜치 (정확히 2개, 추후 A/B harness 1개):
  codex/whipsaw-cost-audit-20260627
  codex/earnings-confirmed-hold-hook-20260627
  (later) codex/concentrated-sizing-broker-ab-harness-20260627

금지: require-X-safety / promotion-flag / gate-review / proxy8/10 브랜치.
1 task = 1 branch = 1 PR. 새 브랜치 생성 전 origin/codex/*-20260627 count 확인.
```

---

## 6. 별도 트랙 (지금 아님, 사용자 인지용)

진단 2차 문제 = **테마 집중 → MDD 구조적 -25% 붙음** (메모리 57%). 이건 selection-level
작업이라 hold-hook보다 큼. **테마 분산 floor**(비상관 주도 테마에서 각각 leader 한 종목씩,
상방 유지하며 상관 drawdown 캡)가 MDD 목표의 진짜 selection lever. 단 hold-hook이 먼저
(measurement-ready). 테마 분산은 hold-hook A/B 결과 후 별도 설계.

---

## 7. 출력 형식

### 7.1 작업 시작 preamble
```
Verification preamble:
  [LOCAL] repo path, last git fetch
  [GITHUB] origin/master SHA, origin/codex/*-20260627 count (>5면 STOP)
  Task: W-AUDIT | HOLD-HOOK (정확히 하나)
  Branch to create, Base
  Files expected / Files forbidden (selection engine 5개 파일)
  Smoke target
```

### 7.2 작업 종료 보고
```
PR <X> complete:
  Branch, commits, files changed (forbidden 0 확인)
  Smoke N/N passed
  W-AUDIT only: estimated_drag_pp_full = <값>, verdict = <값>
  HOLD-HOOK only: applied_count on artifact = <값>
  PR url, CI status
Awaiting: Claude/ChatGPT Pro review, user merge, then cheap broker A/B design.
```

🟦 [END OF PROMPT — Codex starts here] 🟦

---

## 사용 방법 (메타-노트, Codex에 붙이지 마세요)

1. `🟦` 마커 사이 복사 → Codex.
2. **W-AUDIT 먼저.** drag 숫자가 `whipsaw_drag_material` (full ≥ +3pp) 이어야 HOLD-HOOK 진행.
3. W-AUDIT가 minor면 → hold-hook 보류, 사용자 결정 (테마 분산 트랙으로 전환 검토).
4. HOLD-HOOK은 기존 hysteresis 기계 재사용 + `actual_results_score>0` gate가 핵심. broad hysteresis(wash)와 다른 점 명시 요구.
5. cap_safe vs uncapped 분리 측정 필수 (SNDK 36.7% 위험).

## 왜 이 설계가 진단을 정확히 보완하나

| 진단된 문제 | 이 설계의 보완 |
|---|---|
| whipsaw (조기매도 → 비싸게 재매수) — 1차 실패 | W-AUDIT가 비용 정량화 + HOLD-HOOK이 score-dip 매도 차단 |
| broad hold는 reject됨 | actual_results_score>0 + thesis-intact gate (broad 아님) |
| 매도가 가격조정에 발화 | 매도 조건을 **thesis-break**(3m RS 붕괴/MA200 이탈/실적 악화)로 전환 |
| SNDK 36.7% cap 위험 | cap_safe vs uncapped 분리 측정 |
| OOS +12% 같은 짧은 구간 숫자 | full-period broker delta primary, OOS 참고만 |
| 테마 집중 → MDD | §6 별도 트랙 (selection-level, hold-hook 후) |

---

**End of Codex Plan — 2026-06-27 KST. Author: Claude Code.**
