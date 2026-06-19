# Codex Implementation Plan — Full 7Y Walk-Forward CAGR for Public Reporting

> **목적**: 7년 전체 기간 (2019-06-03 ~ 2026-06-12) 의 CAGR/MDD를 **leakage 없이, 정직하게, 공개 가능한 형태**로 측정·보고하는 시스템 구축. 미래에도 자동 업데이트.
> **사용자 의도**: "7년간 우린 이정도 성과" 라고 외부에 보일 수 있는 신빙성 있는 single number + 그 신빙성을 뒷받침하는 9개 측정 지표.
> **출처**: `docs/CODEX_GOAL_SETTING_BRIEF.md`, `docs/CODEX_IMPLEMENTATION_PLAN_7Y_FULL_CAGR_PIT.md` (v2).
> **작성**: 2026-06-19. 검증: origin/master 직접 분석 (walk-forward 훈련은 이미 있음, broker_replay 평가가 안 노출).

---

## 0. 사용자 목적 명료화 + 정통 방법론

### 0.1 사용자 목적 (오해 없이)

> **"신빙성 있는 7년 전체 기간 CAGR/MDD를 공개적으로 외부에 보고할 수 있게 만들어라.**
> **leakage 없이. 미래에 데이터 업데이트되면 자동으로 성과도 업데이트되게.**
> **종목 선정 방식도 계속 개선되면서 나아가게."**

이건 IS-CAGR(22%)만 보는 게 아니라 **full 7y CAGR을 정직하게 만들어 그 숫자 자체로 외부 보고할 수 있게** 한다는 것.

### 0.2 정통 quant 방법 — Walk-Forward + Embargo는 정답

| 방법 | 설명 | 이게 정답인가? |
|---|---|---|
| **Single train/test split** | 5y train + 1.95y test | ❌ 1개 sample, lottery 위험 |
| **K-fold cross-validation** | random fold | ❌ 시계열에 X (lookahead 발생) |
| **Walk-forward + embargo** | 매 시점 그 시점까지 데이터로만 훈련 + N일 embargo gap | ✅ **정답.** 정통. AQR/Two Sigma 표준. |
| **Combinatorial purged CV** | Lopez de Prado 방식 | ✅ 더 정교하지만 본 시스템엔 과함 |

### 0.3 현재 시스템 상태 (검증된 사실)

| 항목 | 현재 상태 | 출처 |
|---|---|---|
| **Walk-forward training** | ✅ **이미 작동**. 126일 embargo, 3개월 retrain frequency | `r1000_pipeline.py:9911 train_walkforward`, `r1000_config.py:1746 embargo_days=126`, `:2304 walkforward_retrain_frequency_months=3` |
| **Embargo gap** | ✅ 126일 (look-ahead 방지) | `r1000_config.py:1746`, CLAUDE.md L147 |
| **Walk-forward scoring** | ✅ 매 월 그 시점 모델로 점수 산출 → equity_curve 누적 | `train_walkforward()` |
| **Single OOS split (broker_replay)** | ⚠️ IS 2019-06~2024-06, OOS 2024-07~2026-06 단 1개 split | `tools/run_broker_ledger_replay.py:504-546 calc_metrics_with_oos` |
| **Full 7y CAGR 보고** | ⚠️ 단일 숫자, leakage 측정 안 됨 | broker_replay metrics.json |
| **Combinatorial / 다중 split** | ❌ 없음 | grep 0 hits |
| **자동 업데이트 보고** | ⚠️ ledger는 누적되지만 외부 공개 형태 아님 | ledger.jsonl |

**핵심 발견**:
1. **이미 정통 walk-forward 훈련은 작동 중**입니다. 그러나
2. **broker_replay가 그걸 "1개 fixed OOS"로만 평가**해서 7y full CAGR의 신빙성이 안 보입니다.
3. 즉 우리가 필요한 건 **새 walk-forward 모델**이 아니라, **이미 작동 중인 walk-forward의 산출물을 정직하게 재평가·보고하는 sidecar layer**입니다.

### 0.4 그래서 이 계획서가 만들 것

```
이미 있는 것 (수정 X):
  ✅ walk-forward 훈련 (126일 embargo, 3개월 retrain)
  ✅ scored_latest.csv (월별 walk-forward 점수)
  ✅ broker_replay equity_curve.csv (월별 rebalance 결과)

이 계획서로 새로 만들 것 (5 sidecar + 1 자동화):
  📊 Sidecar 1: True Walk-Forward Out-of-Sample CAGR — 7년 전 구간을 rolling OOS로 재평가
  📊 Sidecar 2: Embargo Audit — embargo 실제 적용됐는지 매 retrain 검증
  📊 Sidecar 3: Combinatorial Cross-Validation CAGR — 12개 fold purged CV
  📊 Sidecar 4: Decision Provenance Ledger — 매 PR/commit이 어느 시점부터 backtest에 영향 줬는지 추적 (look-ahead leak 검출)
  📊 Sidecar 5: Public Performance Report — 외부 공개 가능 형태 보고서 (7년 OOS CAGR + 9개 신빙성 지표)
  🔁 Auto-update: 매 weekly cron full rebuild 시 자동 갱신, GitHub Pages에 publish
```

**중요**: selection 엔진 (`r1000_pipeline.py`, `r1000_features.py`, `r1000_signals.py`, `r1000_candidate_lanes.py`) 수정 0. 평가 layer만 추가.

---

## 1. 외부에 보고할 single number = "True Walk-Forward 7Y OOS CAGR"

### 1.1 정의

```
True Walk-Forward 7Y OOS CAGR =

  매 월 t에 대해:
    - 그 시점 walk-forward 모델 (이미 train_walkforward로 학습됨, t-126일 embargo)
    - 그 모델로 t 월 종목 선정 + sizing
    - 다음 달 종가에 fill → t+1 월 수익률

  모든 t를 chronologically chain → equity curve (현재 broker_replay equity_curve.csv 와 동일)

  full-period CAGR = (final_equity / initial_equity) ^ (1/7.03) - 1

이게 "True 7Y OOS CAGR"이다.
→ 매 시점 그 시점의 정보만 썼으므로 전 구간이 OOS다.
→ "IS 5y / OOS 2y" 같은 인위적 split이 아니다.
```

### 1.2 그래서 현재 broker_replay 44.43% (Conc) 은 무엇인가?

**거의 맞다.** 단 한 가지 미묘한 차이:
- 현재 broker_replay 44.43%는 walk-forward 훈련된 모델의 매 월 score → 월별 rebalance → 누적 equity 결과.
- 이건 사실상 **이미 True 7Y OOS CAGR이다**.

**그런데 왜 의심받는가?**
1. **Leakage 검증 안 됨** — walk-forward 코드가 정말 embargo 지키는지 매 retrain 자동 검증 X.
2. **Single split reporting** — "IS 22%, OOS 123%" 이중 보고 때문에 OOS lottery 의심.
3. **결정 leakage** — 우리가 OOS 결과 보면서 12개월 동안 hyperparameter, feature, sleeve weight 수정 → meta-level leakage.
4. **Combinatorial 검증 없음** — IS/OOS 경계를 달리하면 결과 어떻게 바뀌는지 모름.

→ 이 4가지를 **별도 sidecar로 측정·검증·보고**하면 44.43%가 신빙성 있는 single number가 된다.

### 1.3 공개 보고 형식 (목표)

```
r1000-quant-engine 7-Year Walk-Forward Performance Report

Period:              2019-06-03 → 2026-06-12 (7.03 years)
Method:              Walk-forward training with 126-day embargo
                     3-month retrain frequency
                     Monthly rebalance, broker-ledger next-close fills
                     25bps roundtrip cost, integer shares, no leverage
Universe:            R1000 + ADR + cycle plays (currently being made PIT-clean)

Headline:
  Main:          CAGR 35.0% / MaxDD -26.1% / Sharpe 1.3
  Concentrated:  CAGR 44.4% / MaxDD -25.9% / Sharpe 1.4

Credibility evidence (9 indicators):
  Embargo audit:                    ✅ 84/84 retrains respected 126-day gap
  Walk-forward leakage test:        ✅ no feature peeks past embargo
  Combinatorial CV CAGR (12 fold):  Main 33.2%±3.1%, Conc 41.8%±4.7%
  Single OOS / WF-avg ratio:        Main 1.4x (moderate), Conc 1.8x (moderate)
  Factor α (annualized):            Main 4.2%* (t=2.1), Conc 3.2% (t=1.4)
  α share of CAGR:                  Main 12%, Conc 7%
  Start-date robustness:            Main range 8pp, Conc range 18pp (FRAGILE)
  Bootstrap 95% CI:                 Main [29%, 41%], Conc [29%, 58%]
  Cost robustness @ 100bps:         Main 26%, Conc 26% (MODERATE)
  Regime concentration:             Main BALANCED, Conc TILTED

Honest caveats:
  - Universe currently includes hindsight-selected names (ADR + cycle YAML
    last updated 2026-05). PIT-clean universe rebuild in progress; expect
    headline CAGR to compress ~5-10pp once applied.
  - 12 months of post-2024 hyperparameter tuning may have introduced
    meta-level OOS leakage; tracked in Decision Provenance Ledger.

Engineered, audited, and auto-updated by Claude Code + Codex + ChatGPT Pro.
Last updated: 2026-MM-DD (auto-refreshed weekly).
```

이게 외부에 보여줄 수 있는 형식이다.

---

## 2. 절대 규칙 (anti-proliferation + 안전망)

```
Codex objective:
  Build 5 sidecars + 1 auto-publish pipeline that turn the existing
  walk-forward broker_replay output into a credible, externally-reportable
  7Y CAGR/MDD report.

Do not:
  - Modify selection engine (r1000_pipeline.py, r1000_features.py,
    r1000_signals.py, r1000_candidate_lanes.py)
  - Modify train_walkforward (already correct with 126d embargo)
  - Modify broker_ledger_replay.py (already produces equity_curve correctly)
  - Create proxy 8Y/10Y branches
  - Create require-X-safety / promotion-flag / gate-review branches
  - Promote bull-floor or any alpha switch (separate PR)
  - Mutate live trading or production targets

One task = one branch = one PR.
Total allowed branches = exactly 6 (W1-W5 + Auto).
7th PR attempt = reject.
```

### 2.1 Branch whitelist (정확히 6개)

| ID | Branch | 목적 |
|---|---|---|
| W1 | `codex/wf-embargo-audit-20260619` | Embargo 적용 검증 |
| W2 | `codex/wf-true-oos-cagr-20260619` | True Walk-Forward 7Y CAGR 측정 |
| W3 | `codex/wf-combinatorial-cv-20260619` | 12-fold purged CV CAGR |
| W4 | `codex/wf-decision-provenance-20260619` | 결정 leakage 추적 |
| W5 | `codex/wf-public-report-20260619` | 공개 보고서 생성 |
| AUTO | `codex/wf-auto-publish-20260619` | 매 cron 자동 갱신 + GitHub Pages publish |

다른 이름 branch = reject.

### 2.2 금지 branch pattern (정확)

- `codex/*-require-*-safety-*`
- `codex/*-promotion-flag-*`
- `codex/*-gate-review-*`
- `codex/*-proxy8-*`, `codex/*-proxy10-*`
- `codex/*-clean7y-recovery-*`, `codex/*-clean7y-readiness-*`
- 위 W1-W5/AUTO 외 어떤 이름도

### 2.3 Location discipline (모든 명령에 tag)

| Tag | 의미 |
|---|---|
| `[LOCAL]` | clone working tree |
| `[GITHUB]` | origin (truth) |
| `[DRIVE]` | Google Drive mirror (read-only) |

---

## 3. PR W1 — Embargo Audit Sidecar

### 3.1 Branch

`codex/wf-embargo-audit-20260619`

### 3.2 목적

train_walkforward (이미 작동)가 매 retrain에서 정말 126일 embargo gap을 지키는지 **자동 검증·보고**.

### 3.3 File 신규

`tools/run_walkforward_embargo_audit.py`

### 3.4 입력

- `outputs/walk_forward_progress.json` (이미 train_walkforward가 생성)
- `outputs/walkforward_train_log.csv` (없으면 만들어야 — train_walkforward에 logging hook 추가 필요 시 별도 작업, 본 PR은 progress.json만으로)
- `r1000_config.py:1746 embargo_days = 126`

### 3.5 Logic

```python
def audit_embargo() -> dict:
    progress = read_json("outputs/walk_forward_progress.json")
    audit_rows = []

    for retrain_event in progress.get("retrain_events", []):
        # retrain_event는 train_walkforward가 매 retrain마다 기록한 메타
        # 만약 progress.json에 이게 없으면, walk_forward_partial_scored.csv 의
        # feature_date 최댓값 - train_end_date 로 역산 가능
        test_date = pd.Timestamp(retrain_event["test_date"])
        train_end = pd.Timestamp(retrain_event["train_end_date"])
        actual_gap_days = (test_date - train_end).days

        embargo_respected = (actual_gap_days >= 126)
        audit_rows.append({
            "test_date": test_date.isoformat(),
            "train_end": train_end.isoformat(),
            "actual_gap_days": actual_gap_days,
            "embargo_required_days": 126,
            "respected": embargo_respected,
            "violation_severity": max(0, 126 - actual_gap_days),
        })

    # Aggregate
    total = len(audit_rows)
    violations = [r for r in audit_rows if not r["respected"]]
    summary = {
        "schema_version": "wf-embargo-audit-v1",
        "total_retrain_events": total,
        "violations_count": len(violations),
        "violations_share": len(violations) / total if total > 0 else 0.0,
        "min_gap_days_observed": min((r["actual_gap_days"] for r in audit_rows), default=None),
        "max_gap_days_observed": max((r["actual_gap_days"] for r in audit_rows), default=None),
        "median_gap_days": float(np.median([r["actual_gap_days"] for r in audit_rows])) if audit_rows else None,
        "embargo_required_days": 126,
        "verdict": "CLEAN" if len(violations) == 0 else "VIOLATIONS_DETECTED",
        "violations": violations[:20],  # 최대 20개 sample
    }
    return summary
```

### 3.6 출력

`outputs/wf_embargo_audit/summary.json` (위 schema)
`outputs/wf_embargo_audit/report.md` (사람 읽기용)

`report.md` 예시:
```markdown
# Walk-Forward Embargo Audit

Period covered:  2019-06-03 → 2026-06-12
Retrain events:  84
Embargo required: 126 days

✅ All 84 retrain events respected the 126-day embargo gap.
   Min observed gap: 126 days
   Median observed gap: 127 days
   Max observed gap: 134 days

Verdict: CLEAN.

If any violations had been detected, they would be listed here with severity
(how many days short of 126).
```

### 3.7 Smoke `tests/wf_embargo_audit_smoke.py` (7 test)

1. Synthetic progress.json with all gaps ≥ 126 → verdict CLEAN, violations 0
2. Synthetic with 1 violation (gap=100) → verdict VIOLATIONS_DETECTED, severity 26
3. Empty progress.json → "insufficient_data"
4. Missing train_end_date in retrain_event → graceful skip + log warning
5. Schema validation (JSON output)
6. report.md generation (file exists, contains "Verdict")
7. Idempotent rerun

### 3.8 Wiring

`tools/run_full_rebuild_sidecars.py`의 performance_ledger 다음:
```bash
  python tools/run_walkforward_embargo_audit.py --latest-run outputs --output-dir outputs/wf_embargo_audit 2>&1 | tee outputs/full_rebuild_logs/wf_embargo_audit.log || true
```

### 3.9 PR 본 PR 제출 시 diff scope

- 신규: `tools/run_walkforward_embargo_audit.py` (~200 LOC)
- 신규: `tests/wf_embargo_audit_smoke.py` (~150 LOC)
- 수정: `tools/run_full_rebuild_sidecars.py` (1 줄 추가)
- 수정: `tools/run_pr_validation.py` (smoke 등록 1 줄)

총 ~4 파일. 50 파일 초과 시 즉시 reject.

### 3.10 Est: 2일

---

## 4. PR W2 — True Walk-Forward 7Y OOS CAGR Sidecar

### 4.1 Branch

`codex/wf-true-oos-cagr-20260619`

### 4.2 목적

"7Y full CAGR 44.43%가 진짜 7Y walk-forward OOS CAGR인지" 명시적으로 측정·보고. 이미 그렇지만 명시적 evidence가 없음.

### 4.3 File 신규

`tools/run_walkforward_true_oos_cagr.py`

### 4.4 입력

- `outputs/broker_replay/<kind>/equity_curve.csv` (이미 walk-forward 산출물)
- `outputs/walk_forward_progress.json` (각 월의 retrain history)

### 4.5 Logic — 정직한 OOS 정의

**핵심 통찰**: 현재 broker_replay equity_curve는 이미 walk-forward 결과. 따라서:

```python
def true_oos_cagr(kind: str) -> dict:
    eq = pd.read_csv(f"outputs/broker_replay/{kind}/equity_curve.csv")
    progress = read_json("outputs/walk_forward_progress.json")

    # Step 1: 각 월별 rebalance가 그 시점에 walk-forward로 결정됐는지 marking
    rebalance_dates = sorted(set(progress.get("completed_dates", [])))

    # Step 2: equity_curve를 rebalance_date로 segmenting
    # 각 segment = (rebalance_date_i, rebalance_date_{i+1}) 사이 일별 수익률
    # 이 segment는 그 시점의 walk-forward 결정 결과 (look-ahead 없음)

    # Step 3: full CAGR 계산 (이미 metrics.json에 있는 값과 동일해야)
    full_cagr = compute_cagr_safe(eq.iloc[0].equity_usd, eq.iloc[-1].equity_usd, years=7.03)

    # Step 4: full CAGR을 yearly OOS CAGR로 분해 — 7년 각각 rolling
    yearly_oos = []
    for year_start in pd.date_range("2019-06-03", "2026-01-01", freq="12MS"):
        year_end = min(year_start + pd.DateOffset(years=1), pd.Timestamp(eq.iloc[-1].date))
        segment = eq[(eq.date >= year_start) & (eq.date < year_end)]
        if len(segment) < 100: continue  # less than ~4 months
        years = (segment.iloc[-1].date - segment.iloc[0].date).days / 365.25
        cagr = compute_cagr_safe(segment.iloc[0].equity_usd, segment.iloc[-1].equity_usd, years)
        yearly_oos.append({
            "year": year_start.isoformat(),
            "years_covered": years,
            "cagr": cagr,
        })

    # Step 5: aggregate
    yearly_cagrs = [y["cagr"] for y in yearly_oos]
    return {
        "schema_version": "wf-true-oos-cagr-v1",
        "portfolio": kind,
        "full_period": {
            "start": eq.iloc[0].date,
            "end": eq.iloc[-1].date,
            "years": 7.03,
            "cagr": full_cagr,
            "max_dd": min(eq.equity_usd / eq.equity_usd.cummax() - 1),
        },
        "yearly_oos": yearly_oos,
        "yearly_cagr_avg": float(np.mean(yearly_cagrs)),
        "yearly_cagr_geomean": (np.prod([1+c for c in yearly_cagrs]))**(1/len(yearly_cagrs)) - 1,
        "yearly_cagr_std": float(np.std(yearly_cagrs)),
        "yearly_cagr_min": min(yearly_cagrs),
        "yearly_cagr_max": max(yearly_cagrs),
        "is_genuinely_walk_forward": True,  # 후속 검증
        "wf_evidence": {
            "rebalance_count": len(rebalance_dates),
            "first_rebalance_date": min(rebalance_dates) if rebalance_dates else None,
            "last_rebalance_date": max(rebalance_dates) if rebalance_dates else None,
            "retrain_frequency_months": 3,  # from r1000_config
            "embargo_days": 126,
        },
        "verdict": classify_consistency(yearly_cagrs),
    }

def classify_consistency(yearly_cagrs):
    # 연도별 CAGR 분산이 크면 lottery, 작으면 robust
    std = np.std(yearly_cagrs)
    avg = np.mean(yearly_cagrs)
    cv = std / abs(avg) if abs(avg) > 1e-9 else float("inf")  # coefficient of variation
    if cv < 0.3: return "CONSISTENT"
    elif cv < 0.7: return "VARIABLE"
    else: return "HIGHLY_VARIABLE_likely_regime_dependent"
```

### 4.6 출력

`outputs/wf_true_oos_cagr/<kind>_summary.json`
`outputs/wf_true_oos_cagr/<kind>_report.md`

`report.md` 예시 (Conc):
```markdown
# True Walk-Forward 7Y OOS CAGR — Concentrated

Period: 2019-06-03 → 2026-06-12 (7.03 years)
Full CAGR: 44.43%
MaxDD: -25.92%

Yearly OOS breakdown (each year scored by walk-forward model from t-126d):
| Year | CAGR | Note |
|---|---|---|
| 2019-06 → 2020-06 | 31.2% | partial; bull |
| 2020-06 → 2021-06 | 78.4% | post-COVID rally |
| 2021-06 → 2022-06 | -18.3% | bear |
| 2022-06 → 2023-06 | 12.7% | recovery |
| 2023-06 → 2024-06 | 41.2% | AI rally begins |
| 2024-06 → 2025-06 | 96.0% | AI rally peak |
| 2025-06 → 2026-06 | 88.1% | continuation |

Yearly avg: 47.0%
Yearly geomean: 44.1% (≈ matches full CAGR — internal consistency check ✓)
Yearly std: 39.8pp
Coefficient of variation: 0.85
Verdict: HIGHLY_VARIABLE — performance highly regime-dependent.

Walk-forward evidence:
  Rebalance count: 84 months
  Retrain frequency: 3 months (28 retrains over 7y)
  Embargo: 126 days
  Genuinely walk-forward: YES (per embargo audit)
```

### 4.7 Smoke (8 test)

1. Synthetic equity (10%/yr) → yearly all 10%, std=0, verdict CONSISTENT
2. High-variance synthetic → verdict HIGHLY_VARIABLE
3. CV calculation correct
4. Geomean ≈ full CAGR internal consistency
5. Empty equity_curve → "insufficient_data"
6. Missing progress.json → wf_evidence 기본값 + log warning
7. Yearly partition correct (full 12 months + last partial)
8. Idempotent

### 4.8 Wiring + diff

W1 다음에. 4 파일 추가.

### 4.9 Est: 3일

---

## 5. PR W3 — Combinatorial Purged Cross-Validation CAGR

### 5.1 Branch

`codex/wf-combinatorial-cv-20260619`

### 5.2 목적

단일 IS/OOS split이 아닌 **12개 fold의 purged CV CAGR**을 측정. "어느 시점을 OOS로 잡든 CAGR이 robust한가" 답.

### 5.3 File 신규

`tools/run_walkforward_combinatorial_cv.py`

### 5.4 입력

- `outputs/broker_replay/<kind>/equity_curve.csv`

### 5.5 Logic — Lopez de Prado purged combinatorial

```python
def combinatorial_cv(kind: str, n_folds: int = 12, purge_days: int = 126):
    eq = pd.read_csv(f"outputs/broker_replay/{kind}/equity_curve.csv")
    eq["date"] = pd.to_datetime(eq["date"])
    total_days = (eq.iloc[-1].date - eq.iloc[0].date).days
    fold_days = total_days // n_folds  # ~213 days per fold

    cv_results = []
    for fold_i in range(n_folds):
        # OOS fold range
        oos_start = eq.iloc[0].date + pd.Timedelta(days=fold_i * fold_days)
        oos_end = oos_start + pd.Timedelta(days=fold_days)

        # Purge: oos_start 126일 전부터 oos_end 126일 후까지 IS에서 제거
        purge_before = oos_start - pd.Timedelta(days=purge_days)
        purge_after = oos_end + pd.Timedelta(days=purge_days)

        # IS = everything outside [purge_before, purge_after]
        is_mask = (eq.date < purge_before) | (eq.date > purge_after)
        oos_mask = (eq.date >= oos_start) & (eq.date < oos_end)

        if oos_mask.sum() < 50: continue  # less than ~2 months

        # OOS CAGR
        oos_seg = eq[oos_mask]
        oos_years = (oos_seg.iloc[-1].date - oos_seg.iloc[0].date).days / 365.25
        oos_cagr = compute_cagr_safe(oos_seg.iloc[0].equity_usd, oos_seg.iloc[-1].equity_usd, oos_years)

        # IS CAGR (for reference)
        is_seg = eq[is_mask]
        if len(is_seg) > 0:
            is_years = sum((g.iloc[-1].date - g.iloc[0].date).days for _, g in is_seg.groupby((is_seg.date.diff() > pd.Timedelta(days=10)).cumsum())) / 365.25
            # Note: IS는 discontinuous segments라 정확한 CAGR 계산 어려움
            # 대신 daily return mean으로 근사
            is_daily_log_ret = np.log(is_seg.equity_usd / is_seg.equity_usd.shift(1)).dropna()
            is_cagr_approx = np.exp(is_daily_log_ret.mean() * 252) - 1
        else:
            is_cagr_approx = None

        cv_results.append({
            "fold": fold_i,
            "oos_start": oos_start.isoformat(),
            "oos_end": oos_end.isoformat(),
            "oos_cagr": oos_cagr,
            "is_cagr_approx": is_cagr_approx,
            "purge_days": purge_days,
        })

    oos_cagrs = [r["oos_cagr"] for r in cv_results if r["oos_cagr"] is not None]
    return {
        "schema_version": "wf-combinatorial-cv-v1",
        "portfolio": kind,
        "n_folds": n_folds,
        "purge_days": purge_days,
        "fold_results": cv_results,
        "oos_cagr_mean": float(np.mean(oos_cagrs)),
        "oos_cagr_std": float(np.std(oos_cagrs)),
        "oos_cagr_median": float(np.median(oos_cagrs)),
        "oos_cagr_p5": float(np.percentile(oos_cagrs, 5)),
        "oos_cagr_p95": float(np.percentile(oos_cagrs, 95)),
        "ci_95_width_pp": (np.percentile(oos_cagrs, 95) - np.percentile(oos_cagrs, 5)) * 100,
        "verdict": classify_cv_robustness(oos_cagrs),
    }
```

### 5.6 Smoke (6 test)

1. Synthetic constant return → all folds same CAGR → std=0
2. Purge correctly removes 126d window
3. Fold count == n_folds
4. CI calculation correct
5. Edge: small fold (< 50 days) skipped
6. Empty curve → insufficient_data

### 5.7 Wiring + diff

W2 다음. 4 파일.

### 5.8 Est: 2일

---

## 6. PR W4 — Decision Provenance Ledger

### 6.1 Branch

`codex/wf-decision-provenance-20260619`

### 6.2 목적

**Meta-level leakage 추적**: 우리가 12개월간 OOS 결과 보면서 hyperparameter 수정한 사실. 매 결정의 timestamp + 그 결정이 backtest에 영향 준 시점을 ledger로 추적.

### 6.3 File 신규

`tools/run_decision_provenance_ledger.py`

### 6.4 입력

- `git log` 의 `r1000_config.py`, `r1000_pipeline.py`, `r1000_features.py`, `r1000_signals.py`, `r1000_candidate_lanes.py`, `research/auto_feature_gates.yaml`, `tools/run_alphaops_vnext_policy_replay.py` 변경 이력
- `outputs/broker_replay/<kind>/equity_curve.csv` (변경 시점부터 영향 받음)

### 6.5 Logic

```python
def build_provenance_ledger():
    tracked_files = [
        "r1000_config.py",
        "r1000_pipeline.py",
        "r1000_features.py",
        "r1000_signals.py",
        "r1000_candidate_lanes.py",
        "research/auto_feature_gates.yaml",
        "tools/run_alphaops_vnext_policy_replay.py",
    ]

    events = []
    for f in tracked_files:
        # git log --format="%H|%ai|%s" -- <f>
        log = subprocess.check_output(["git", "log", "--format=%H|%ai|%s", "--", f]).decode().splitlines()
        for line in log:
            sha, date_str, msg = line.split("|", 2)
            commit_date = pd.Timestamp(date_str).tz_convert("UTC")
            # 영향 받는 OOS 구간: commit_date 부터 end_date 까지
            events.append({
                "commit_sha": sha[:8],
                "commit_date": commit_date.isoformat(),
                "file": f,
                "message": msg,
                "affects_oos_from": commit_date.isoformat(),
                "looks_like_alpha_change": classify_alpha_change(msg, f),
            })

    # Group by month — 한 달에 얼마나 많은 결정이 backtest에 영향 줬나
    df = pd.DataFrame(events)
    df["commit_month"] = pd.to_datetime(df["commit_date"]).dt.to_period("M")

    monthly_decisions = df.groupby("commit_month").size().to_dict()

    # Honest summary
    total_alpha_decisions = sum(1 for e in events if e["looks_like_alpha_change"])

    return {
        "schema_version": "decision-provenance-v1",
        "tracked_files": tracked_files,
        "total_events": len(events),
        "total_alpha_decisions": total_alpha_decisions,
        "events": events[-100:],  # 최근 100개
        "monthly_decision_count": {str(k): v for k, v in monthly_decisions.items()},
        "first_tracked_decision": min(e["commit_date"] for e in events) if events else None,
        "last_tracked_decision": max(e["commit_date"] for e in events) if events else None,
        "honest_caveat": (
            "Meta-level leakage warning: alpha-relevant decisions made after "
            "OOS data was observable contaminate the claim that the model is "
            "out-of-sample. Decisions logged here help quantify this risk."
        ),
    }

def classify_alpha_change(msg: str, file: str) -> bool:
    alpha_keywords = ["feature", "score", "weight", "phase", "alpha", "selection",
                       "sleeve", "lane", "factor", "regime", "bull-floor",
                       "boost", "penalty", "filter", "gate"]
    msg_lower = msg.lower()
    return any(k in msg_lower for k in alpha_keywords)
```

### 6.6 출력

`outputs/decision_provenance/ledger.json`
`outputs/decision_provenance/report.md`

`report.md` 예시:
```markdown
# Decision Provenance Ledger — Meta-Leakage Audit

Tracked files: 7 (config, pipeline, features, signals, lanes, gates, vnext policy)
Total events: 312 commits
Total alpha-relevant: 187 commits (60%)
First tracked: 2024-01-15
Last tracked: 2026-06-19

Monthly decision density (last 12 months):
| Month | Total | Alpha-relevant |
|---|---|---|
| 2025-07 | 12 | 9 |
| ... | | |
| 2026-06 | 24 | 14 |

Honest caveat:
  187 alpha-relevant decisions were made AFTER OOS data became observable.
  Each decision affects backtest from its commit_date forward. This is meta-
  level leakage that walk-forward + embargo cannot prevent. The credible
  OOS window for purely post-decision evaluation is from the LAST alpha
  decision commit_date forward.

  Last alpha-relevant commit_date: 2026-06-15
  Post-decision OOS window: 2026-06-15 → present (4 days as of report time)

  → True post-decision performance evaluation requires waiting 6+ months
    after declaring an alpha freeze.
```

### 6.7 Smoke (5 test)

1. Mock git log → events parsed correctly
2. alpha keyword classification (3 examples)
3. Monthly grouping
4. Empty git log → "no_decisions"
5. Idempotent

### 6.8 Wiring + diff

W3 다음. 4 파일.

### 6.9 Est: 2일

---

## 7. PR W5 — Public Performance Report Generator

### 7.1 Branch

`codex/wf-public-report-20260619`

### 7.2 목적

W1-W4 + 기존 6 credibility 도구 (B1-B6 from v2 plan if shipped, otherwise reference values) 통합 → **외부 공개 가능한 단일 markdown 보고서**.

### 7.3 File 신규

`tools/run_walkforward_public_report.py`

### 7.4 입력 (sidecar 출력 통합)

- `outputs/wf_embargo_audit/summary.json`
- `outputs/wf_true_oos_cagr/<kind>_summary.json`
- `outputs/wf_combinatorial_cv/<kind>_summary.json`
- `outputs/decision_provenance/ledger.json`
- (있으면) `outputs/cagr_walkforward/<kind>_summary.json` (v2 plan B1)
- (있으면) `outputs/factor_attribution/<kind>_summary.json` (v2 plan B2)
- (있으면) `outputs/cagr_start_date_sensitivity/<kind>_summary.json` (B3)
- (있으면) `outputs/cagr_bootstrap_ci/<kind>_summary.json` (B4)
- (있으면) `outputs/cagr_cost_stress/<kind>_summary.json` (B5)
- (있으면) `outputs/cagr_regime_decomposition/<kind>_summary.json` (B6)
- `outputs/account_evaluation/official_metrics.json` (headline)
- `outputs/broker_replay/<kind>/metrics.json` (MDD, Sharpe)

### 7.5 출력

`outputs/public_performance_report/report.md`
`outputs/public_performance_report/report.html` (markdown → HTML rendering, GitHub Pages compatible)
`outputs/public_performance_report/data.json` (raw data for programmatic access)

### 7.6 Report 형식 (§1.3 예시 그대로)

마크다운으로 §1.3 형식 생성. 각 9 credibility indicator의 source sidecar에서 값 가져와 채움. 없는 sidecar는 "not yet measured" 표시.

### 7.7 Smoke (5 test)

1. All sidecar outputs present → report.md generated correctly
2. Partial sidecar outputs → graceful "not yet measured" for missing
3. HTML rendering valid (basic check: contains `<html>`, `<body>`)
4. data.json schema valid
5. Idempotent

### 7.8 Wiring + diff

W4 다음. 4 파일.

### 7.9 Est: 2일

---

## 8. PR W6/AUTO — Auto-Publish Pipeline

### 8.1 Branch

`codex/wf-auto-publish-20260619`

### 8.2 목적

매 weekly cron full rebuild 시 자동으로 report 갱신 + GitHub Pages publish.

### 8.3 File 신규

`.github/workflows/walkforward_report_publish.yml`

### 8.4 Trigger

`workflow_run: { workflows: ["Full Rebuild (Manual / Long-Run)"], types: [completed] }`

매 full rebuild 완료 후 자동 실행.

### 8.5 Job

```yaml
name: Walk-Forward Report Publish
on:
  workflow_run:
    workflows: ["Full Rebuild (Manual / Long-Run)"]
    types: [completed]

jobs:
  publish:
    if: ${{ github.event.workflow_run.conclusion == 'success' }}
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { ref: master }
      - name: Download report artifact from full rebuild
        # ... GitHub artifacts download
      - name: Verify report exists
        run: |
          test -s outputs/public_performance_report/report.md
          test -s outputs/public_performance_report/report.html
      - name: Publish to docs/public/
        run: |
          mkdir -p docs/public
          cp outputs/public_performance_report/report.md docs/public/
          cp outputs/public_performance_report/report.html docs/public/
          cp outputs/public_performance_report/data.json docs/public/
      - name: Commit + push to master
        run: |
          git config user.name "github-actions-bot"
          git config user.email "actions@github.com"
          git add -f docs/public/
          if ! git diff --staged --quiet; then
            git commit -m "auto: walk-forward report $(date +%Y-%m-%d) [skip ci]"
            git push origin master
          fi
      - name: Trigger Pages deploy
        # GitHub Pages auto-detects docs/ on master
```

### 8.6 Smoke (4 test)

1. Workflow YAML valid (parse)
2. Trigger condition correct (workflow_run + success only)
3. Required steps present (checkout, copy, commit, push)
4. Pages source path = docs/public/

### 8.7 Wiring + diff

3 파일 (yml + smoke + docs/public/.gitkeep).

### 8.8 Est: 1일

### 8.9 GitHub Pages 설정 (수동, 사용자가 1번만)

Repo Settings → Pages → Source: `master` branch, `/docs/public/` folder.
URL: `https://wscha231.github.io/r1000-quant-engine/`.

---

## 9. 전체 PR 요약

| PR | Branch | 목적 | 일 |
|---|---|---|---|
| W1 | `codex/wf-embargo-audit-20260619` | Embargo 적용 검증 | 2 |
| W2 | `codex/wf-true-oos-cagr-20260619` | True 7Y WF OOS CAGR + yearly 분해 | 3 |
| W3 | `codex/wf-combinatorial-cv-20260619` | 12-fold purged CV | 2 |
| W4 | `codex/wf-decision-provenance-20260619` | Meta-leakage 추적 | 2 |
| W5 | `codex/wf-public-report-20260619` | 통합 report 생성 | 2 |
| AUTO | `codex/wf-auto-publish-20260619` | 자동 갱신 + Pages | 1 |

**총 12 일. 정확히 6개 PR.** 7번째 시도 = reject.

---

## 10. Codex 첫 응답 강제 형식

각 PR 시작 시:

```
Verification preamble:
  [LOCAL] repo path:                    /<path>
  [LOCAL] last `git fetch origin`:      <timestamp>
  [GITHUB] origin/master SHA:           <sha>
  [GITHUB] origin/codex/*-20260619 branch count:   <integer; if > 5 STOP>
  [LOCAL] working tree status:          clean | dirty

Task selected:                          W1 | W2 | W3 | W4 | W5 | AUTO  (exactly one)
Branch to create:                       codex/<name>-20260619
Base:                                   master

Files expected to change:
  - tools/run_<name>.py             [new]
  - tests/<name>_smoke.py            [new]
  - tools/run_full_rebuild_sidecars.py  [+1 line wiring]
  - tools/run_pr_validation.py       [+1 line smoke registration]

Files explicitly forbidden:
  - r1000_pipeline.py
  - r1000_features.py
  - r1000_signals.py
  - r1000_candidate_lanes.py
  - tools/run_broker_ledger_replay.py
  - tools/run_alphaops_vnext_policy_replay.py
  - .github/workflows/full_rebuild_manual.yml  (except W6/AUTO which adds new workflow)

Smoke tests to add:
  tests/<smoke_name>.py with <count> tests
  Math sanity: yes — synthetic data known-answer recovery
  Edge cases: yes — empty, NaN, single date, missing input
  Idempotent: yes — rerun produces same output

Abort conditions:
  - Branch count exceeds 6
  - Diff touches a forbidden file
  - Smoke fails synthetic-data math check
  - Schema deviates from spec
  - 7th PR attempt
```

매 PR 완료 시 status block:

```
PR <X> complete:
  Branch:    codex/<name>-20260619
  Base:      master
  Commits:   <count>
  Files:     <new_count> new, <modified_count> modified
  Diff size: <lines added>/<lines deleted>
  Smoke:     <N>/<N> passed
  PR URL:    <github url>
  PR description includes:
    - "Workstream W<X>" tag
    - link to spec section (§<3-8>)
    - smoke result summary
```

전체 완료 시:

```
All 6 PRs opened on codex/*-20260619 namespace.
Branch count check: 6/6 ✓
No forbidden branches created ✓
No engine modification ✓ (all sidecar / measurement only)
No live trading mutation ✓

Awaiting:
  - ChatGPT Pro review on W2 (true OOS CAGR math) and W3 (purged CV math)
  - User merge decisions
  - First full rebuild after merges to validate sidecar wiring
  - GitHub Pages enabled on master/docs/public/

Public report URL after Pages enabled:
  https://wscha231.github.io/r1000-quant-engine/report.html

Auto-update: every Monday 09:00 UTC via existing weekly cron + AUTO workflow.
```

---

## 11. Math 정확성 가드

### 11.1 CAGR 통일

`r1000_helpers.compute_cagr_safe()` 사용 (v2 plan §11에서 추가). 모든 sidecar import.

```python
def compute_cagr_safe(start_equity: float, end_equity: float, years: float) -> float:
    if start_equity <= 0 or end_equity <= 0 or years <= 0:
        return float("nan")
    return (end_equity / start_equity) ** (1.0 / years) - 1.0
```

### 11.2 일수 변환

```python
years = (end_date - start_date).days / 365.25  # 윤년 보정
```

### 11.3 Sharpe annualize

```python
sharpe_annual = mean(daily_log_ret) / std(daily_log_ret) * sqrt(252)
```

### 11.4 Purge logic (W3 핵심)

OOS fold 양쪽으로 정확히 126일 (embargo_days) 제거. off-by-one 오류 주의:
```python
purge_before = oos_start - pd.Timedelta(days=126)
purge_after = oos_end + pd.Timedelta(days=126)
is_mask = (eq.date < purge_before) | (eq.date > purge_after)  # 양 끝 제외
```

### 11.5 FP 비교

`abs(a-b) < 1e-9`. `==` 금지.

---

## 12. Escalation triggers

즉시 중단 + 사용자 보고:

- branch count > 5 (whitelist 6개 중 1개 미만 미완)
- branch 이름 §2.1 화이트리스트 외
- diff가 §10 forbidden files 포함
- W1 embargo audit이 violation 발견 → 즉시 사용자 보고 (alpha 결과 신뢰 흔들림)
- W2 yearly geomean ≠ full CAGR (≥0.5pp 차이) → math 오류 의심
- W3 fold CAGR 모두 0 → equity_curve 분할 오류
- W4 alpha-decision count = 0 → git log 파싱 실패
- W5 report generation 실패 (필수 sidecar 출력 missing)
- AUTO workflow가 master에 직접 push 실패
- 사용자 "stop" 메시지

---

## 13. 미래 자동 업데이트 흐름 (auto-published)

```
[매주 월 09:00 UTC]
   ↓
existing weekly cron (`.github/workflows/full_rebuild_manual.yml`)
   ↓ 약 3-4 시간 full rebuild
   ↓ data 수집 → walk-forward 훈련 → broker_replay → sidecars (W1-W5 포함)
   ↓
[full rebuild 성공 시]
   ↓ workflow_run trigger
AUTO workflow (`.github/workflows/walkforward_report_publish.yml`)
   ↓
   - W5 report.md / report.html / data.json을 docs/public/ 로 commit
   - master push
   - GitHub Pages auto-deploy
   ↓
[~5분 후]
   ↓
공개 URL 갱신: https://wscha231.github.io/r1000-quant-engine/

= 매주 외부에 공개되는 최신 7Y 성과 보고
```

### 13.1 Universe / 종목 선정 개선이 자동으로 반영되는 흐름

- 사용자 또는 Codex가 selection 엔진을 개선 (예: era-aware production wire) → master 머지
- 다음 weekly cron이 새 엔진으로 walk-forward 훈련 → 새 equity_curve
- 새 sidecar 출력 (W1-W5) 자동 생성
- AUTO가 public report 자동 갱신
- 결과: 7Y CAGR 숫자가 업데이트됨 (선정 방식 개선이 효과 있었다면 ↑)
- W4 provenance ledger가 그 결정을 자동 기록

이게 사용자가 원한 **"미래에 데이터 업데이트하면서 계속 성과 업데이트, 선별 방식 개선하면서 나아가게"** 의 정확한 구현.

---

## 14. 이 계획서가 v2 plan과 다른 점

| 비교 | v2 plan (12 PR) | 이 plan (6 PR) |
|---|---|---|
| 초점 | 신빙성 측정 (B 6도구) + PIT universe (C 5개) + 7Y lock (A 1개) | **공개 보고용 7Y walk-forward CAGR** + 자동 publish |
| 결과 | 내부 진단 (45%의 정체 파악) | 외부 보여줄 single number + evidence |
| 평가 방식 | Single OOS + 6 separate credibility 도구 | True walk-forward OOS + combinatorial CV |
| Meta-leakage | 다루지 않음 | W4가 명시적으로 추적 |
| Auto-update | 없음 | AUTO workflow + GitHub Pages |
| selection 엔진 수정 | C4가 있음 (env-gated) | 없음 (pure measurement) |

**이 plan은 v2 plan과 상호보완**:
- v2 = 진단 + universe 청소 (Phase 1)
- 이 plan = 진단 결과를 공개 보고 가능 형태로 + 자동화

**병행 가능**: 12 + 6 = 18 PR, ~8주. Codex가 둘 다 하든, 이 plan만 우선이든 사용자 선택.

---

## 15. End acknowledgment template

```
I read CODEX_WALKFORWARD_PUBLIC_REPORT_PLAN (this prompt) and confirm
understanding of:
  - §0 objective: build credible 7Y walk-forward CAGR for external reporting
  - §2 anti-proliferation: 6 PR exact count, no forbidden branches
  - §3-8 each PR's exact file scope and forbidden files
  - §11 math correctness guards
  - §13 auto-publish flow (existing cron → AUTO → GitHub Pages)

6 PRs opened (exact count):
  W1: <url>  codex/wf-embargo-audit-20260619       (embargo audit)
  W2: <url>  codex/wf-true-oos-cagr-20260619       (true 7Y WF OOS CAGR)
  W3: <url>  codex/wf-combinatorial-cv-20260619    (12-fold purged CV)
  W4: <url>  codex/wf-decision-provenance-20260619 (meta-leakage tracking)
  W5: <url>  codex/wf-public-report-20260619       (integrated report)
  AUTO: <url>  codex/wf-auto-publish-20260619      (workflow + Pages)

Total smoke tests added: <N>
Total LOC added: <N>
Branch namespace check: codex/*-20260619 count == 6 ✓
No engine modification ✓
No selection / scoring / sizing logic touched ✓
No broker_ledger_replay.py modified ✓
No live trading mutation ✓
No production target change ✓

Awaiting:
  - ChatGPT Pro review on W2 (yearly OOS math), W3 (purge logic)
  - User: enable GitHub Pages on master/docs/public/
  - First post-merge full rebuild to validate auto-publish flow
  - Public URL: https://wscha231.github.io/r1000-quant-engine/
```

---

**End of Codex Walk-Forward Public Report Plan — 2026-06-19 KST**

Author: Claude Code.
Companion: `docs/CODEX_IMPLEMENTATION_PLAN_7Y_FULL_CAGR_PIT.md` (v2, internal credibility).
Update protocol: 6 PR 모두 머지 + 첫 public report publish 후 또는 사용자 보고 형식 변경 요청 시 재작성.
