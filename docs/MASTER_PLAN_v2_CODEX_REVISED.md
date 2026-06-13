# MASTER PLAN v2 — Codex Review에 의한 정정 + 보완

> 2026-06-11 · author: Claude (session 01EFuqqTBYNezRzskPLMHdKU)
> Supersedes: `MASTER_PLAN_CODEX_HANDOFF_20260611.md` (v1)
> Trigger: Codex 5.5 review surfaced 4 substantive corrections + 1 false claim.
> Implementer: Codex 5.5 still writes detailed code; this is the corrected spec.

---

## 0. Codex Review 자가검증

| Codex 주장 | 코드 증거 | 판정 |
|---|---|---|
| `sidecar_only_verify.yml` 부재 → `alphaops_replay_sidecars_manual.yml` 사용 | `ls -la .github/workflows/sidecar_only_verify.yml` → exists (commit `f7306b2`, master `b8e645c`) | ❌ Codex 오류 (checkout stale 추정) |
| `run_broker_gap_attribution.py` 이미 존재 → "new"가 아니라 "extend" | `ls -la tools/run_broker_gap_attribution.py` → 15,884 bytes, 함수 9개 (target_forward_stats, broker_stats 등) | ✅ Codex 정확. v1의 "new file" 표기 오류 |
| CASH 갭은 broker가 아니라 operating book exporter에서 발생 | `grep -i "cash" tools/build_operating_target_books.py` → **0건** (303줄 전체에 CASH 처리 없음) | ✅ Codex 정확. **결정적 증거**. v1의 "broker가 CASH 무시"는 잘못된 묘사. 실체는 "operating book이 CASH overlay를 통째로 누락" |
| 더 최신 baseline 27088007617 (main 33.46%/-26.23%, conc 40.61%/-29.94%) + verified 27086825471 (main 30.76%/-34.83%, conc 42.82%/-29.34%) 사용해야 함 | 내가 본 27247439447은 outdated. Codex가 갖고 있는 baseline이 더 신선 | ✅ Codex 정확. **v1 평가의 기준점이 stale했음** |
| Concentrated champion filter가 N=3/winner-take-all 100% 강제 → cash 0.039% | `run_broker_ledger_replay.py`에는 이미 우회 flag(`--disable-concentrated-champion-filter`) 있음. **하지만 operating book exporter에는 champion filter가 별도 경로** | ✅ Codex 정확. v1의 P1.1 우회는 broker replay만 커버. operating book에서 champion filter 적용 단계가 별도 |
| 사용자 정식 게이트: main CAGR ≥ 30% & MDD ≥ -25%, conc CAGR ≥ 45% & MDD ≥ -25% | v1은 "broker baseline 대비 +0.5pp"만 명시했고 절대 목표를 빠뜨림 | ✅ Codex 정확. v1 약점 |

**총평**: Codex review가 본질적으로 정확. v1 plan의 5개 substantive 결함이 있었고, 그중 가장 큰 건 **outdated baseline 사용**(27247439447 → 응당 27088007617/27086825471). 단 sidecar_only_verify.yml은 실재하므로 그 부분 plan은 유지.

---

## 1. v1 → v2 변경 사항 요약

| v1 entry | v2 정정 |
|---|---|
| Baseline: target 30.62% / broker main 20.80% (run 27247439447) | **Latest verified baselines**: full rebuild 27088007617 (main 33.4570%/-26.2339%, conc 40.6084%/-29.9424%), fast replay 27086825471 (main 30.7638%/-34.8303%, conc 42.8243%/-29.3356%) |
| Target gates: "broker baseline 대비 +0.5pp" | **Absolute targets** (사용자 메시지): main CAGR ≥ 30% AND MDD ≥ -25% / concentrated CAGR ≥ 45% AND MDD ≥ -25%. **27088007617에서 main은 CAGR pass / MDD fail (-1.23pp 부족)**, conc는 CAGR fail (-4.4pp) / MDD fail (-4.94pp). 갭이 구체적으로 보임 |
| "build_operating_target_books가 CASH를 renormalize" | **"build_operating_target_books가 CASH 토큰을 인식하지 않음"** (코드 grep -i cash → 0건). 결과는 v1과 같으나 진단이 정확해야 fix 위치가 맞음 |
| W1.1 "new file run_broker_gap_attribution.py" | **"extend 기존 파일"**: fee_drag, integer_share_residual, fill_lag_slippage, cash_timing 외에 **`target_book_export_gap`**(backtest_metrics.avg_cash_weight − operating_book monthly cash) 신규 분해항 추가 |
| Champion filter 우회는 P1.1에서 `run_broker_ledger_replay.py --disable-concentrated-champion-filter`로 끝남 | **불완전**. operating book exporter에도 champion filter 경로 있음 → concentrated CASH 0.039%의 진짜 원인. 별도 fix 필요 (§3.3) |
| W3.2 macro-history validation의 episode 분포: 2000·2008·2011·2015·2018·2020·2022 | 유지. 단 episode label은 `r1000_long_crisis_liquidity.SPLIT_BOUNDARIES`에 이미 정의된 train/val/test/holdout 위에 episode 윈도를 매핑 |
| sidecar_only_verify.yml 사용 | **유지** (Codex 주장 반박: 파일 실재) |

---

## 2. 정정된 W0 — 게이트 + baseline lock

### 2.1 SHIP 게이트를 절대 목표로 교체 (Codex 정확한 spec)

`run_local.py`:
- 기본 `--gate-mode broker` (target은 escape hatch).
- Source: `outputs/broker_replay/{main,concentrated}/metrics.json`.
- **절대 게이트** (사용자 정식 목표):
  ```python
  TARGET_GATES = {
      "main":         {"cagr_min": 0.30, "mdd_min": -0.25},  # MDD_min은 "이보다 deep 가면 fail" 의미
      "concentrated": {"cagr_min": 0.45, "mdd_min": -0.25},
  }
  ```
- 추가 게이트 (퇴행 방지): broker baseline 대비 `dCAGR >= +0.5pp AND dMDD >= -3pp`.
- 두 게이트 모두 통과해야 SHIP. 하나만 통과면 PARTIAL.

### 2.2 Baseline lock (v1 정정)

```python
BROKER_BASELINE = {
    # Latest verified fast replay (run 27086825471)
    "verified_fast_replay": {
        "run_id": 27086825471,
        "main": {"cagr": 0.3076, "sharpe": 1.1941, "max_dd": -0.3483, "avg_cash": 0.2431},
        "concentrated": {"cagr": 0.4282, "sharpe": 1.2954, "max_dd": -0.2934, "avg_cash": 0.3469},
    },
    # Latest full rebuild (run 27088007617) — current production reference
    "latest_full_rebuild": {
        "run_id": 27088007617,
        "main": {"cagr": 0.3346, "sharpe": 1.2511, "max_dd": -0.2623, "avg_cash": 0.2725},
        "concentrated": {"cagr": 0.4061, "sharpe": 1.3250, "max_dd": -0.2994, "avg_cash": 0.4193},
    },
}
```
- Verdict는 `latest_full_rebuild` 대비 측정 (가장 최근 official 증거).
- `verified_fast_replay`는 fast loop A/B용.

### 2.3 OOS lock — 임계값 재근거

v1의 8pp 임의 임계 → **데이터 기반 캘리브레이션**으로 변경:
- `oos_start: 2024-07-01` (8y 윈도의 마지막 2y).
- 임계값 = `max(5pp, baseline_run의 in-sample CAGR × 0.20)`. 즉 베이스라인 자체의 IS CAGR이 35%면 7pp 허용, 25%면 5pp 허용. 절대 임계가 아니라 baseline-relative.
- 정당화: in-sample이 높을수록 sampling noise도 큼 → 절대 임계는 over-tune 검출이 어려움.

---

## 3. 정정된 W1 — Operating book CASH 보존 (진짜 root cause)

### 3.1 진단 — Codex가 짚은 갭의 정확한 위치

| Layer | avg cash | 비고 |
|---|---|---|
| `backtest_metrics.json::avg_cash_weight` | 21.34% (run 27247439447, main) | cash overlay 적용된 백테스트 결과 |
| `outputs/reports/operating_main_target_book.csv` 월별 cash 평균 | **5.63%** | **여기서 16pp 손실** |
| `outputs/broker_replay/main/metrics.json::avg_cash_weight` | 5.94% | operating book에 충실 (≈ 5.63%) |

**Root cause**: `build_operating_target_books.py` (303줄)가 CASH 토큰을 한 번도 다루지 않음. backtest_metrics의 cash overlay가 export 과정에서 통째로 누락.

### 3.2 Fix — operating book exporter의 CASH 보존

`tools/build_operating_target_books.py`:
- 입력 `main_monthly_weights.csv` / `concentrated_strategy_holdings.csv`의 `CASH` 행(또는 `1.0 - sum(stock_weights)`로 추정된 cash)을 explicit row로 보존.
- 출력 `operating_*_target_book.csv`에 `ticker=CASH` 행을 매 rebalance_date마다 작성.
- 검증: stock weight 합계 == `1 - cash_weight` (±1e-6 허용). 위반 시 명시적으로 `RuntimeError`.

### 3.3 Fix — concentrated champion filter의 CASH 손실 (별도 경로)

`run_broker_ledger_replay.py`에는 이미 `--disable-concentrated-champion-filter` 있음 (P1.1, commit 3baa7d0). 하지만 **operating book exporter에 champion filter가 별도로 적용되는 경로**가 있어 conc CASH 0.039% (run 27247439447) → 41.93% (run 27088007617) 사이 거대 변동.
- 트레이스: `build_operating_target_books.py` 안에서 `champion`/`filter`/`target_stock_names` 호출 추적.
- Fix: champion 적용 후에도 stock 합계 == `1 - cash_weight` 보장. champion으로 N개를 뽑되 그 N개의 합 비중을 `1 - cash` 로 스케일.

### 3.4 Gap attribution 확장 (Codex가 옳음 — extend)

`tools/run_broker_gap_attribution.py` (기존, 진단 수준):
- 추가 분해항:
  1. `fee_drag` (기존)
  2. `integer_share_residual`
  3. `fill_lag_slippage`
  4. `cash_timing` (broker realized cash vs operating book cash)
  5. **`target_book_export_gap`** (backtest_metrics.avg_cash_weight − operating book monthly cash) ← **신규, root cause 정확히 측정**
  6. `residual` (must be < 30% of total gap)
- Acceptance: 합계가 total gap의 ±1pp/yr 안에 들어옴. Fix 후 `target_book_export_gap`가 0에 수렴.

### 3.5 Acceptance gate

- run 27088007617의 main MDD -26.23%가 -25% 게이트를 통과하려면 +1.23pp 회수 필요.
- 27247439447 → 27086825471 사이 main cash 21% 회복으로 MDD 가 -32.65% → -34.83% (오히려 악화!). cash만으로 안 풀린다는 증거.
- 그래서 W1은 **CASH export gap 측정 + 수정**, 그 다음 broker MDD 변화를 봐야 정확한 기여도가 나옴.
- 게이트 통과 못 하면 W1b(execution band) + W3(leader lifecycle)로 진행.

---

## 4. 정정된 W2 — Crisis governor 검증 (사실상 v1 유지)

이 절은 v1과 동일. **fast loop 재dispatch가 단일 다음 액션**. 변경 없음.

단 한 줄 추가:
- crisis features 재빌드 후 best_thresholds.json의 `crisis_gate` 값이 0.45+ 인지 확인 (재정규화 스케일 검증). 0.30 근처면 stale.

---

## 5. 정정된 W3 — Leader lifecycle (v1 유지 + 게이트 명시)

v1과 동일. 단 게이트 추가:
- rotation_lag 중앙값 ≤ 40 거래일
- premature_sell_excess_return: exited 종목의 +126d 평균 excess가 음수 (즉 잘 팔았다)
- shakeout_guard_recovery_rate ≥ 55%
- reentry_capture_rate ≥ 60%

이 4개 중 3개 이상 fail이면 leader state machine 튜닝 우선. 모두 pass면 leader는 손대지 말 것.

---

## 6. W4 — Data moat (v1 유지, 단 브랜치 unification 명시 우선순위 ↑)

v1과 동일하되 **순서 변경**: 다른 모든 작업 전에 `codex/alphaops-integrated-replay` 브랜치를 `claude/...`에 머지. 이유:
- ETF N-PORT historical PIT (codex 브랜치) 없으면 W4 data moat 결손
- Top7 manager lane (codex 브랜치) 없으면 W3 leader audit이 한쪽 정보만 봄
- Phase 11 toggle, coverage gate, data catalog 등 다른 valuable infrastructure가 codex 브랜치에 잠겨있음

**액션**: W0 끝나면 즉시 `git merge origin/codex/alphaops-integrated-replay` (충돌 해결 후 fast loop으로 재검증).

---

## 7. W5 — Subtractive cleanup (v1 유지)

v1과 동일. 게이트 안정 후 실행. 단 우선순위 명확화:
1. **price IO 통합** (W1 진행 중 즉시 — SHA1 버그가 같은 위치에서 또 나오면 안 됨)
2. Phase 11/3/5 코드 표면 삭제 (W2 끝나고)
3. 사이드카 67 → ~25 (W3 끝나고)
4. 27k줄 모놀리스 split (최후, byte-identical 게이트)

---

## 8. W6 — Future robustness rails (Codex가 빠뜨린 부분 — 강조 ↑)

Codex plan에는 거의 없음. v1 유지하되 **W3 직후 implement** (W4 W5 전):
1. Parameter stability gate (이미 있는 `parameter_stability.csv` → SHIP 게이트화)
2. Rolling re-verdict (월별 cron, broker baseline + OOS lock 대비)
3. Decay monitoring (12m rolling IC, halving → 리뷰 플래그)
4. yfinance redundancy (Alpaca failover)

---

## 9. 정정된 sequencing

| 순서 | Work | v1 대비 변경 |
|---|---|---|
| 1 | W0.1-0.3 게이트 + OOS lock (절대 목표 + relative gates) | 절대 목표 명시 강화, OOS lock baseline-relative |
| 2 | W2.1 fast loop 재dispatch (sidecar_only_verify.yml, 27247439447 source) | 변경 없음 |
| 3 | **W4 branch unification** (codex 브랜치 머지) | **신규 우선순위** |
| 4 | W1.1-1.4 operating book CASH 보존 + champion filter cash + gap attribution extend | "new file" → "extend" 정정, root cause 정확화 |
| 5 | W3 leader lifecycle audit | 게이트 명시 추가 |
| 6 | W6 robustness rails | v1 우선순위에서 위로 |
| 7 | W5.1 price IO 통합 | 1순위로 이동 (다른 W5 전) |
| 8 | W1b execution band grid | 변경 없음 |
| 9 | W2.2-2.3 macro per-episode + liquidity | 변경 없음 |
| 10 | W5.2-5.4 Phase 삭제, 사이드카 다이어트 | 변경 없음 |
| 11 | W5.5 monolith split | 최후 |

---

## 10. Hard rules (v1 유지)

변경 없음. 추가 한 줄: **outdated baseline은 plan의 가장 큰 단일 결함이다. 매 plan 갱신 시 최근 success Full Rebuild + verified fast replay의 run_id를 먼저 명시**.

---

## 11. Codex가 옳았던 점 (감사 명시)

- Operating book이 CASH를 처리하지 않는다는 정확한 진단 (코드 grep로 confirmed).
- Concentrated champion filter의 cash 손실이 별도 경로 (broker replay flag만으로는 부족).
- Target gates의 절대 목표(30% / -25%, 45% / -25%) 명시 필요.
- `run_broker_gap_attribution.py`는 이미 존재 (v1의 "new file" 오기).
- W0 게이트 교체 → fast replay 우선 → full rebuild는 collector/freshness 필요 시만. (v1과 동일하지만 더 깔끔하게 표현)

## 12. Codex가 놓친 점 (보완)

- W6 future robustness rails (parameter stability, rolling re-verdict, IC decay, data redundancy).
- W4 brand unification의 우선순위 (codex 브랜치의 ETF N-PORT, Top7 lane 등 가치 있는 인프라 잠금).
- W3 leader lifecycle 측정의 구체 게이트 (4지표 중 3 fail이면 튜닝).
- `sidecar_only_verify.yml` 실존 (Codex가 못 봤다고 한 것은 stale checkout).

---

## 13. 다음 실행 액션 (코드 없이)

1. `git fetch origin codex/alphaops-integrated-replay && git merge origin/codex/alphaops-integrated-replay` (W4 우선순위 격상 반영).
2. Codex 5.5에게 이 문서 (`MASTER_PLAN_v2`) 전달 — W0부터 코드 작성 시작.
3. W0 코드 머지 후 `sidecar_only_verify.yml` dispatch (source_run_id=27088007617, ref=현재 브랜치) — 첫 번째 broker gate 측정.
