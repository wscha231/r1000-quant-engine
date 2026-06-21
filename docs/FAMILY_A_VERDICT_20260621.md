# Family A 판정 — fast-crash 월간 cash-overlay 무력 (A1/A2 FAIL)

- 작성일: 2026-06-21 KST / Claude
- runs: A1 #216 `27887125658` (DD breaker), A2 #217 `27887129839` (VIX floor). 둘 다 completed/success, broker-ledger next-close.
- baseline: run #214 `27873592126` (master `a3dbd01`, clean 7Y).

## 결과 (broker-ledger)

| | Main CAGR | Main MaxDD | avg_cash | Conc CAGR | Conc MaxDD | Conc cash |
|---|---:|---:|---:|---:|---:|---:|
| baseline #214 | 34.73% | −26.05% | 26.4% | 45.47% | −24.59% | 41.9% |
| **A1** DD-breaker 0.12→0.08 / floor 0.15→0.25 | 34.28% | **−27.18%** | 26.6% | 44.37% | −24.70% | 41.9% |
| **A2** VIX floor 0.10→0.20 / 0.25→0.40 | 34.27% | **−27.18%** | 26.6% | 44.40% | −24.70% | 41.9% |
| floor (절대) | ≥35% | ≥−25% | — | ≥50% | ≥−25% | — |

window 2019-07-01 → 2026-06-18 (6.97y), fill next_close, cost 25bps/side.

## 판정: 둘 다 FAIL, 가설 반증

- override는 **실제 적용 확인됨**: `run_log_tail.txt` → `[fast-crash-env] applied R1000_DRAWDOWN_BREAKER_LEVEL_1_THRESHOLD: 0.12 -> 0.08`, `..._CASH_FLOOR: 0.15 -> 0.25`.
- 그럼에도:
  1. **A1 ≈ A2** (Main MDD −27.179 vs −27.183, CAGR 34.277 vs 34.268) — 서로 다른 레버가 동일 결과 = outcome에 무력.
  2. **avg_cash 불변** (26.6% vs baseline 26.4%) — cash floor 0.25/0.40으로 올렸으나 평균현금 미증가.
  3. **Main MaxDD 오히려 악화** (−27.18%), CAGR floor·MDD floor 모두 미달.

## 근본 원인 (구조적, 깨끗한 결론)

- `max_dd_peak_date 2020-02-19 → max_dd_trough_date 2020-03-18` = **28 calendar days.**
- 포트폴리오 = **월간 리밸런스.** DD breaker / VIX floor는 리밸런스 시점에만 cash를 재배분.
- COVID 급락이 한 리밸런스 사이클 내에서 완결 → cash floor가 발동할 시점엔 이미 trough 통과. Main MDD는 **크래시 직전 보유 포지션**이 결정하며, 사후 반응형 월간 overlay로는 선제 방어 불가.
- ∴ **"현금 레버를 더 세게" 방향(monthly cash overlay)은 Main MDD에 대해 죽은 길.** A3(dd-velocity)·선제 de-risk 류만 유효.

## 부수 발견

- Conc MaxDD는 baseline·A1·A2 모두 floor 통과(−24.6~−24.7%). **Conc 결함은 MDD가 아니라 CAGR shortfall(−5.6pp)** → Family B(bull cash drag, avg_cash 41.9%) 영역.
- 엔진 self-correction router가 Conc 구조적 underinvestment에 대해 자체 실험 3건을 큐잉(승인대기): `conc_continuation_winner_relaxation`, `conc_bull_floor_stock_min`, `conc_reentry_quality`. Family B 작업과 정렬됨.
- Codex가 `1b18955 feat: expose family b cash drag env hooks` 이미 머지 — Family B env-override 준비됨.
- 주의: A/B control(8e092b4 빈-env)을 안 돌려서 baseline −26.05% → −27.18%의 1.1pp drift는 레버가 아니라 commit/merge 차이일 가능성. within-experiment 비교(A1 vs A2)는 clean하며 레버 무력이 확정 결론.

## 다음 (MDD 갈림길 — user 결정 필요)
월간 overlay가 반증됐으므로 Main MDD ≤ −25%는:
- (a) **dd-velocity / intra-month stop** — 월간보다 빠른 반응형 트리거(신규 피처 = FULL).
- (b) **선제 de-risk** — 고VIX 레짐 진입 시 리밸런스에서 gross를 미리 축소(반응이 아닌 선행 지표).
- (c) **daily position stop in replay** — 종목별 일간 손절을 broker-replay에 추가.
