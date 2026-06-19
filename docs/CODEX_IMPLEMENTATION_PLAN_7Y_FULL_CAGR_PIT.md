# Codex Implementation Plan v2 — Clean 7Y Baseline + Full CAGR Credibility + PIT Universe

> **v1 (`9abe721a`)의 오류를 사용자 지적으로 정정한 버전.**
> 변경: (1) "official SHIP" → "clean 7Y research/A-B baseline" (2) 8Y + 10Y proxy 둘 다 차단 (3) bull-floor promote를 A1에서 제거 (별도 alpha PR) (4) anti-proliferation 규칙을 §0 첫 줄 (5) preamble 강화 (6) 측정만/엔진 수정 금지 강조.
> 출처 brief: `docs/CODEX_GOAL_SETTING_BRIEF.md`, `docs/CODEX_PROMPT_48H_ACTION_PACK.md`.

---

## 🟦 [PASTE TO CODEX FROM HERE] 🟦

## 0. Codex Objective + 절대 규칙 (가장 먼저 읽고 따를 것)

```
Codex objective:
  Lock the system to clean 7Y broker-ledger research/A-B baseline,
  measure Full CAGR credibility with six sidecar tools,
  and rebuild PIT-safe universe inputs.

Do not build proxy 8Y/10Y evidence.
Do not create more safety/gate/require-X branches.
Do not mutate live trading, production targets, or broker execution.
Do not promote bull-floor or any alpha switch in this plan
  (alpha promotion = separate PR, NOT in this 12-PR scope).

One task = one branch = one PR.
Total allowed branches = exactly 12 (A1, B1-B6, C1-C5).
13th PR attempt = reject.
```

### 0.1 Anti-Proliferation Rules (모든 명령 전 확인)

```
Before creating ANY branch:
  [GITHUB] Count existing origin/codex/*-20260619 branches:
    if count > 5 AND current task is not one of the 12 planned PRs: STOP, report user.
    if count == 12 AND new branch is being created: STOP, report user.

NEVER create branches matching these patterns:
  - codex/*-require-*-safety-*
  - codex/*-promotion-flag-*
  - codex/*-gate-review-*
  - codex/*-proxy8*-*
  - codex/*-proxy10*-*
  - codex/*-clean7y-recovery-*    (lock 결정 후 무의미)
  - codex/*-clean7y-readiness-*   (lock 결정 후 무의미)

Allowed branches ONLY (exact names):
  Workstream A:  codex/lock-7y-window-20260619
  Workstream B:  codex/cagr-walkforward-20260619
                 codex/cagr-factor-alpha-20260619
                 codex/cagr-start-date-sensitivity-20260619
                 codex/cagr-bootstrap-ci-20260619
                 codex/cagr-cost-stress-20260619
                 codex/cagr-regime-decomp-20260619
  Workstream C:  codex/pit-r1000-membership-20260619
                 codex/pit-adr-scanner-20260619
                 codex/pit-13f-form4-candidates-20260619
                 codex/universe-pit-integration-20260619
                 codex/universe-rebuild-semiannual-20260619

Any other branch name = reject.
```

### 0.2 Location Discipline (Action Pack §0과 동일)

| Tag | 의미 |
|---|---|
| `[LOCAL]` | 너의 clone working tree |
| `[GITHUB]` | `github.com/wscha231/r1000-quant-engine` 원격 (truth source) |
| `[DRIVE]` | Google Drive mirror (read-only) |

모든 명령에 위치 tag. 예외 없음.

---

## 1. 결정 컨텍스트 (왜 v2가 필요한가)

### 1.1 사용자 결정

- ✅ **clean 7Y broker-ledger = 연구 + A-B baseline.** Production promotion / live SHIP은 별도 user governance 결정.
- ❌ **proxy 8Y AND 10Y window 확장 작업 둘 다 중단.** `pit_universe_label` 없이 window 늘리기는 survivorship bias 키우기.
- ✅ **Full CAGR 신빙성을 6개 sidecar 측정 도구로 입증** — 도구는 **측정**이지 **개선**이 아님 (B는 selection 엔진 수정 0).
- ✅ **PIT universe 재구성**이 진짜 alpha 신뢰성 lever — C에서만 selection/universe 엔진 수정 허용.

### 1.2 v1에서 정정된 사항

| 정정 | v1 표현 | v2 표현 |
|---|---|---|
| Authority | "공식 SHIP window" | "clean 7Y research/A-B baseline" |
| Proxy 차단 | 8Y만 | 8Y AND 10Y 둘 다 |
| Bull-floor | A1 review에 포함 | 이 plan 범위 밖 — 별도 alpha PR |
| 엔진 수정 | §5.0에 묻혀있음 | §0 첫 줄 + §3 명시 |

### 1.3 검증된 사실

| 사실 | 출처 |
|---|---|
| Bull-floor A/B 검증 — Main IS +1.45pp, Conc IS +1.12pp | `origin/master:cloud_results/performance_ledger/ledger.jsonl` row 4 |
| Bull-floor가 master에서 여전히 default OFF | `tools/run_alphaops_vnext_policy_replay.py:2712 default=False` |
| 최신 run IS-CAGR 22.36% (퇴보) | ledger row 5 |
| ADR/cycle YAML 마지막 손큐레이션 2026-05 | git log |
| Historical universe membership file 코드 path 있음, 데이터 없음 | `r1000_pipeline.py:2854-2882` |
| Form4/13F는 score에만, universe 결정에 안 들어감 | grep 0 hits |

**참고**: bull-floor가 default OFF 그대로인 건 알려진 문제다. 하지만 그 promote는 **이 12-PR plan 범위 밖** — 별도 alpha PR로 사용자가 결정할 일이다. 여기선 건드리지 말 것.

---

## 2. 3개 Workstream 개요 (12 PR, 6주)

### 2.1 Workstream A — 7Y Lock (1 PR, 1일)

8Y/10Y proxy 시도가 무의식적으로 재개되는 걸 코드로 차단.

### 2.2 Workstream B — Full CAGR Credibility 측정 (6 PR, 10일)

**측정만**. selection/scoring/sizing 엔진 일절 수정 금지.

### 2.3 Workstream C — PIT Universe 재구성 (5 PR, 18일)

**여기서만 selection/universe 엔진 수정 허용**. PIT-safe universe가 진짜 alpha 신뢰성 핵심.

---

## 3. 절대 금지 (위반 시 즉시 중단)

| 금지 | 검출 방법 |
|---|---|
| **§0.1 외 branch 생성** | branch 생성 전 `[GITHUB] gh api` count check |
| **task 하나에 2 PR 이상** | 각 §4, §5, §6의 PR이 정확히 1개 |
| **자기 PR 머지** | `gh pr merge` 금지 |
| **`master` 직접 push** | branch-protect 있지만 실수 방지 |
| **Workstream A에서 bull-floor 코드 수정** | A1 diff는 `r1000_config.py`, `tools/run_account_evaluation.py`, `.github/workflows/full_rebuild_manual.yml`만. `tools/run_alphaops_vnext_policy_replay.py` 수정 시 reject |
| **Workstream B에서 selection 엔진 수정** | B는 `r1000_pipeline.py`, `r1000_features.py`, `r1000_candidate_lanes.py`, `r1000_signals.py` 전부 수정 금지. 신규 `tools/run_cagr_*.py` 와 `tests/cagr_*_smoke.py` 만 생성 |
| **Workstream B에서 broker_replay 수정** | `tools/run_broker_ledger_replay.py` 절대 수정 금지 (cost_stress 도구는 subprocess로 호출만) |
| **smoke 없는 commit** | 각 tool은 `tests/<name>_smoke.py` 필수 + `tools/run_pr_validation.py` 등록 |
| **schema 자유 변경** | §7 schema 정확히 따라야 |
| **live trading 코드 활성화** | 어느 `auto_trade_allowed`, `production_activation_allowed` 도 true로 바꾸지 말 것 |
| **production target 수정** | `PORTFOLIO_GOAL_TARGETS`, `PORTFOLIO_GOAL_GATES` 직접 수정 금지 |
| **broker execution 수정** | `tools/run_broker_ledger_replay.py`, `tools/run_account_order_preview.py` 절대 수정 금지 |

---

## 4. Workstream A — 7Y Lock (1 PR)

### 4.1 PR A1 — `codex/lock-7y-window-20260619`

**목적**: 8Y AND 10Y proxy 확장 시도가 무의식적으로 재개되지 못하게 코드 잠금.

**범위 (오직 이것만, 다른 건 X)**:

#### 수정 파일 1: `r1000_config.py`

새 상수 추가:
```python
# Window lock — 2026-06-19 user 결정. 8Y/10Y proxy 확장은
# pit_universe_label_clean blocker가 풀리기 전까지 시도 금지
# (proxy = survivorship bias = F4 위반).
CLEAN_BACKTEST_WINDOW_YEARS = 7.0
CLEAN_BACKTEST_START_DATE = "2019-06-03"
CLEAN_BACKTEST_END_DATE_POLICY = "latest_close"
CLEAN_BACKTEST_ROLE = "research_and_ab_baseline"  # NOT "official SHIP"

PROXY_EXTENSION_BLOCKED_YEARS = [8.0, 10.0]
PROXY_EXTENSION_BLOCKER_REASON = "pit_universe_label_missing"
PROXY_EXTENSION_UNLOCK_REQUIRES = [
    "data_raw/historical_universe_membership.parquet exists",
    "PIT_UNIVERSE_LABEL_CLEAN flag = true in data_readiness",
]
```

#### 수정 파일 2: `tools/run_account_evaluation.py`

hard-fail 가드 추가:
```python
def _enforce_window_lock(broker_metrics: dict[str, Any]) -> None:
    """Window lock guard — refuse proxy 8Y/10Y baselines.

    Per 2026-06-19 user decision: clean 7Y is the research/A-B baseline;
    proxy 8Y/10Y is survivorship-biased and blocked until PIT universe
    label is clean. See r1000_config.PROXY_EXTENSION_BLOCKED_YEARS.
    """
    try:
        from r1000_config import (
            CLEAN_BACKTEST_WINDOW_YEARS,
            PROXY_EXTENSION_BLOCKED_YEARS,
        )
    except Exception:
        return  # fallback context — let it pass
    years = float(broker_metrics.get("years") or 0.0)
    pit_clean = bool(broker_metrics.get("pit_universe_label_clean", False))
    if years > CLEAN_BACKTEST_WINDOW_YEARS + 0.05 and not pit_clean:
        for blocked in PROXY_EXTENSION_BLOCKED_YEARS:
            if abs(years - blocked) < 0.5:
                raise RuntimeError(
                    f"window_years={years:.2f} matches blocked proxy window "
                    f"{blocked:.1f}y AND pit_universe_label_clean=false. "
                    f"Per r1000_config.PROXY_EXTENSION_BLOCKED_YEARS, this run "
                    f"is rejected as a survivorship-biased baseline. Complete "
                    f"Workstream C (PIT universe) before attempting extension."
                )

# 호출 시점: summarize_portfolio() 안에서 broker_metrics 읽은 직후.
```

#### 수정 파일 3: `.github/workflows/full_rebuild_manual.yml`

backtest_years input validation 단계 (steps 처음 부분):
```yaml
      - name: Reject proxy-window backtests
        run: |
          BY="${{ inputs.backtest_years }}"
          if [ "$BY" = "8" ] || [ "$BY" = "10" ]; then
            echo "ERROR: backtest_years=$BY is a blocked proxy window."
            echo "       Use backtest_years=7 (clean A-B baseline) until"
            echo "       Workstream C (PIT universe) lands."
            exit 2
          fi
```

#### 수정 파일 4 (있으면): `tools/run_eight_year_backtest_readiness.py`

Codex가 이미 만든 도구가 있으면 lock_status 키만 추가:
```python
summary["lock_status"] = "CLEAN_7Y_LOCKED_UNTIL_PIT_UNIVERSE_CLEAN"
summary["lock_reason"] = "pit_universe_label_missing"
summary["unblock_steps"] = ["complete_workstream_C"]
```

#### 추가 금지 파일 (A1에서 수정하면 reject)

- `tools/run_alphaops_vnext_policy_replay.py` — 여기 만지면 bull-floor 또는 다른 alpha 변경.
- `r1000_pipeline.py`, `r1000_features.py`, `r1000_signals.py`, `r1000_candidate_lanes.py` — selection 엔진.
- `tools/run_broker_ledger_replay.py` — execution.
- 그 외 어떤 `tools/run_*.py` 든.

#### Smoke: `tests/seven_year_lock_smoke.py` (8 test)

1. `CLEAN_BACKTEST_WINDOW_YEARS == 7.0` 정확
2. `CLEAN_BACKTEST_ROLE == "research_and_ab_baseline"` (SHIP 표현 없음)
3. `PROXY_EXTENSION_BLOCKED_YEARS == [8.0, 10.0]`
4. `_enforce_window_lock`이 years=8.0 + pit_clean=False 일 때 raise
5. `_enforce_window_lock`이 years=7.0 일 때 pass
6. `_enforce_window_lock`이 years=8.0 + pit_clean=True 일 때 pass (미래 unlock)
7. workflow YAML이 backtest_years=8 reject 단계 포함 (YAML parse)
8. import 가능

#### Success criteria

- ✅ `[GITHUB]` PR open, smoke 8/8 pass
- ✅ Diff scope: 정확히 4개 파일 (3 수정 + 1 신규 smoke), `r1000_pipeline.py` 등 5개 금지 파일 0 변경
- ✅ ChatGPT Pro review = "scope correct, no bull-floor / no alpha mutation / no proxy extension"
- ✅ User 머지

**Estimated**: 1 day.

---

## 5. Workstream B — Full CAGR Credibility 측정 도구 6개 (6 PR)

### 5.0 공통 규칙 (B에 절대)

| 규칙 | 검증 |
|---|---|
| **selection/scoring/sizing 엔진 수정 0** | diff에 `r1000_pipeline.py`, `r1000_features.py`, `r1000_signals.py`, `r1000_candidate_lanes.py`, `r1000_main_v2.py` 변경 시 reject |
| **broker_replay 코드 수정 0** | `tools/run_broker_ledger_replay.py` diff = 0 (B5에서 subprocess 호출만) |
| **각 도구 = 새 sidecar** | `tools/run_cagr_*.py` 또는 `tools/run_factor_*.py` 신규 |
| **input = `outputs/broker_replay/<kind>/equity_curve.csv`** | 신규 데이터 입력 X (B2는 yfinance factor proxy 추가) |
| **output = `outputs/<tool_name>/<kind>_summary.{json,md}`** | §7 schema 정확히 |
| **`run_full_rebuild_sidecars.py`에 non-fatal wire** | `\|\| true` 끝 + `tee log` |
| **`compute_cagr_safe()` 헬퍼 통일** | B1-B6 모두 import (§11.1) |
| **per-portfolio** | main + concentrated 둘 다 |

### 5.1 PR B1 — Walk-forward OOS CAGR

**Branch**: `codex/cagr-walkforward-20260619`
**File**: `tools/run_cagr_walkforward.py`

**Math**: 단일 1.95년 OOS vs 4개 1년 rolling test CAGR 평균. **모델 retrain 안 함** (equity_curve 시간 구간만 분할).

```
rolling test windows (NOT walk-forward retrain — equity curve segmentation):
  2023: 2023-01-01 → 2023-12-31
  2024: 2024-01-01 → 2024-12-31
  2025: 2025-01-01 → 2025-12-31
  2026_partial: 2026-01-01 → end_date

per window i:
  CAGR_i = (eq_end / eq_start)^(1/years) - 1
  MDD_i  = min(eq / cummax(eq) - 1)
  Sharpe_i = mean(daily_log_ret) / std(daily_log_ret) * sqrt(252)

walk_forward_cagr_avg     = arithmetic_mean(CAGR_i)
walk_forward_cagr_geomean = (prod(1+CAGR_i))^(1/n) - 1
inflation_indicator       = oos_single_window_cagr / walk_forward_cagr_avg

verdict:
  if inflation_indicator < 1.3: "single_oos_consistent_with_rolling_avg"
  elif inflation_indicator < 2.0: "single_oos_moderately_inflated"
  else: "single_oos_lottery_vs_rolling_avg"
```

**Caveat docstring 의무**:
```
NOTE: This is "rolling-window CAGR over the same trained model's equity curve",
not "walk-forward CAGR with model retraining". True walk-forward retrain CAGR
requires re-running r1000_pipeline 4 times — that is a separate alpha PR,
NOT in this measurement plan.
```

**Smoke** (`tests/cagr_walkforward_smoke.py`, 6 test):
1. 4 window 정확히 식별
2. CAGR 수식 정확 (synthetic equity curve known answer)
3. avg/geomean 둘 다 정확
4. inflation_indicator = single_OOS / wf_avg
5. partial year (2026) last available date 사용
6. empty curve → "insufficient_data" status

**Wire**: `run_full_rebuild_sidecars.py` performance_ledger 다음.

**Estimated**: 2 days.

### 5.2 PR B2 — Factor / Alpha Attribution

**Branch**: `codex/cagr-factor-alpha-20260619`
**File**: `tools/run_factor_attribution.py`

**Math**:
```
inputs:
  equity_curve.csv → daily portfolio simple returns
  yfinance daily adj close: SPY, QQQ, SMH, IWM, IWF, IWD, GLD, TLT

regression:
  r_p_t = α + β1·r_SPY + β2·(r_QQQ - r_SPY) + β3·(r_SMH - r_QQQ) +
          β4·(r_IWM - r_SPY) + β5·(r_IWF - r_IWD) + β6·r_GLD + β7·r_TLT + ε

  OLS via numpy.linalg.lstsq + se = sqrt(diag(σ²(X'X)⁻¹))
  t-stat = β_i / se_i
  R² = 1 - SS_res/SS_tot

annualize:
  α_annual = α_daily * 252
  alpha_share_of_full_cagr = α_annual / full_cagr  (참고: 베타 share = 1 - alpha share)

verdict:
  alpha_significant = (|alpha_tstat| > 1.96)
  if alpha_share > 0.30 AND alpha_significant: "HIGH_ALPHA"
  elif alpha_share > 0.15 AND alpha_significant: "MODERATE_ALPHA"
  elif alpha_share > 0 AND alpha_significant: "LOW_ALPHA_SIGNIFICANT"
  else: "LOW_ALPHA_OR_INSIGNIFICANT_high_β"
```

**Dependency**: yfinance (이미 repo에서 사용). statsmodels 없으면 numpy lstsq + manual SE.

**Smoke** (`tests/factor_attribution_smoke.py`, 7 test):
1. 합성 α=10%, β_SPY=1.0 → 복원 (±0.5pp / ±0.05)
2. portfolio == 1.0 × SPY → α≈0, β_SPY≈1.0, R²≈1.0
3. random walk → α not significant
4. annualization 정확 (α_daily*252)
5. t-stat 계산 정확 (known X, y)
6. NaN/missing factor day 정확 drop
7. empty curve → "insufficient_data"

**Wire**: B1 다음.

**Estimated**: 3 days.

### 5.3 PR B3 — Start-Date Sensitivity

**Branch**: `codex/cagr-start-date-sensitivity-20260619`
**File**: `tools/run_cagr_start_date_sensitivity.py`

**Math**:
```
start_dates = [
  "2019-06-03",  # current default
  "2019-12-02",
  "2020-03-23",  # COVID bottom
  "2020-06-01",
  "2021-01-04",  # high growth period
  "2021-06-01",
  "2022-01-03",
]

per start_date sd:
  if sd < equity_curve.start: skip with reason "before_curve_start"
  segment = curve[curve.date >= sd]
  CAGR_sd = (segment.end_eq / segment.start_eq)^(1/segment.years) - 1
  MDD_sd  = min(segment.eq / cummax(segment.eq) - 1)

cagr_range_pp = (max(cagr_list) - min(cagr_list)) * 100
mdd_range_pp  = (max(mdd_list) - min(mdd_list)) * 100  (in absolute value)

robustness_score:
  if cagr_range_pp < 5: "ROBUST"
  elif cagr_range_pp < 15: "MODERATE"
  else: "FRAGILE"
```

**Smoke** (5 test):
1. 7 start_dates 모두 처리
2. before_curve_start skip + reason
3. range_pp 정확
4. robustness threshold (5, 15)
5. 동일 곡선 → 모든 start에서 동일 → range=0 → ROBUST

**Estimated**: 1 day.

### 5.4 PR B4 — Block Bootstrap CI

**Branch**: `codex/cagr-bootstrap-ci-20260619`
**File**: `tools/run_cagr_bootstrap_ci.py`

**Math**:
```
daily log returns: r_t = log(eq[t]/eq[t-1])
block_size = 20  (monthly cycle 보존)
n_resamples = 1000
seed = np.random.default_rng(20260615)

n_blocks_needed = ceil(total_days / block_size)
for i in 1..1000:
  blocks = rng.choice(all_blocks, size=n_blocks_needed, replace=True)
  resampled_log_returns = concat(blocks)[:total_days]
  cum_growth = exp(sum(resampled_log_returns))
  CAGR_i = cum_growth^(1/years) - 1

distribution = sorted(CAGR_i)
median = percentile(50)
p5 = percentile(5)
p95 = percentile(95)
ci_95_width_pp = (p95 - p5) * 100

credibility_score:
  if ci_95_width_pp < 10: "TIGHT"
  elif ci_95_width_pp < 25: "MODERATE"
  else: "LOOSE"
```

**Smoke** (6 test):
1. seed reproducibility (같은 seed 두 번 → 정확히 동일 CI)
2. 균등 수익률 (10%/yr) → CI 좁음
3. high vol 수익률 → CI 넓음
4. block_size 20 + n_resamples 1000 정확
5. NaN log return 처리
6. empty curve → "insufficient_data"

**Estimated**: 1 day.

### 5.5 PR B5 — Cost Stress Test

**Branch**: `codex/cagr-cost-stress-20260619`
**File**: `tools/run_cagr_cost_stress.py`

**주의**: 이 도구는 `broker_replay`를 **재실행**한다 (5번). 비용 높음. Default OFF.

**Logic**:
```
cost_levels_bps = [25, 50, 75, 100, 150]

for cost_bps in cost_levels_bps:
  output_dir = f"outputs/cost_stress/{cost_bps}bps/{portfolio}"
  subprocess.run([
    "python", "tools/run_broker_ledger_replay.py",
    "--target-book", target_book_path,
    "--price-cache", "cache_prices",
    "--portfolio-kind", portfolio,
    "--output-dir", output_dir,
    "--fill-mode", "next_close",
    "--cost-bps", str(cost_bps),
    "--max-fill-lag-days", "7",
  ], check=False)
  metrics = read_json(f"{output_dir}/metrics.json")
  collect((cost_bps, metrics.cagr, metrics.max_dd, metrics.sharpe))

sensitivity_pp_per_bp = (cagr_at_25 - cagr_at_150) / (150 - 25) * 100

robustness_score:
  if cagr_at_100 > 0.25: "ROBUST"
  elif cagr_at_50 > 0.30: "MODERATE"
  else: "FRAGILE"
```

**중요**: `broker_replay` 코드 자체는 절대 수정하지 않는다 (subprocess 호출만).

**Smoke** (5 test, broker_replay 호출은 mock):
1. 5 cost level 정확 호출 (`subprocess.run` mock으로 args 검증)
2. metrics aggregate 정확
3. sensitivity_pp_per_bp 계산
4. robustness threshold
5. broker_replay 실패 graceful (한 level fail해도 나머지 진행)

**Wire**: `full_rebuild_manual.yml` workflow input `enable_cost_stress=false` default. `run_full_rebuild_sidecars.py`에서 env `${ENABLE_COST_STRESS}` 체크 후 실행.

**Estimated**: 2 days.

### 5.6 PR B6 — Regime Decomposition

**Branch**: `codex/cagr-regime-decomp-20260619`
**File**: `tools/run_cagr_regime_decomposition.py`

**Math**:
```
inputs:
  equity_curve.csv (daily)
  operating target book → rebalance_date의 regime_state column
  → 일별로 ffill: 그 월의 regime을 다음 rebalance까지 모든 거래일에 적용

per regime in {strong_bull, bull, neutral, bear, deep_bear, unknown}:
  days = count of rows with this regime
  if days == 0: skip
  daily_simple_returns = list of returns for those days
  mean_daily_return = mean(...)
  std_daily_return = std(...)
  annualized_return_pct = mean_daily_return * 252 * 100
  annualized_vol_pct = std_daily_return * sqrt(252) * 100
  sharpe = annualized_return / annualized_vol  (if vol > 0)
  share = days / total_days
  contribution_to_full_cagr_pp =
    mean_daily_return * days / total_days * 252 * 100

concentration:
  positive_contributions = [c for c in contributions if c > 0]
  top_regime_share = max(positive_contributions) / sum(positive_contributions)
  if top_regime_share > 0.7: "DIRECTIONAL"
  elif top_regime_share > 0.5: "TILTED"
  else: "BALANCED"
```

**Smoke** (6 test):
1. 3 regime 균등 → BALANCED
2. bull 90% → DIRECTIONAL
3. regime ffill 정확 (rebalance_date 사이 보간)
4. missing regime column graceful
5. NaN daily return 처리
6. 0-days regime skip

**Estimated**: 1 day.

### 5.7 Workstream B 정리

| PR | Tool | Est | Output verdict field |
|---|---|---|---|
| B1 | walkforward CAGR | 2d | `inflation_indicator`, single_vs_avg verdict |
| B2 | factor attribution | 3d | `alpha_share_of_full_cagr`, HIGH/MODERATE/LOW_ALPHA |
| B3 | start-date sensitivity | 1d | `cagr_range_pp`, ROBUST/MODERATE/FRAGILE |
| B4 | bootstrap CI | 1d | `ci_95_width_pp`, TIGHT/MODERATE/LOOSE |
| B5 | cost stress | 2d | `cagr_at_100bps`, ROBUST/MODERATE/FRAGILE |
| B6 | regime decomposition | 1d | `top_regime_share`, BALANCED/TILTED/DIRECTIONAL |

총 10일. 6개 sidecar가 자동으로 매 rebuild마다 출력 생성.

**선택 PR B7 — Combined Credibility Report**는 v2에서 **삭제** (12 PR 규칙 위반). 통합 report가 필요하면 별도 결정 후 별도 PR.

---

## 6. Workstream C — PIT Universe 재구성 (5 PR)

### 6.0 C 전용 권한 + 규칙

- **C에서만** selection/universe 엔진 수정 허용 (B에서 금지).
- 단 C4의 `build_universe_monthly` 수정은 **env-gated default OFF** 필수.
- live production target은 절대 mutate 금지.
- 모든 새 데이터 산출물은 "candidate"로 라벨링 (official 아님).

### 6.1 PR C1 — Historical R1000 Membership ETL

**Branch**: `codex/pit-r1000-membership-20260619`
**File**: `tools/build_pit_r1000_membership.py`

**Data source**: SEC EDGAR + iShares IWB 13F filings 분기별.

**Output**: `data_raw/historical_universe_membership_candidate.parquet` (NOT "official").

Schema:
```
columns: [ticker, cik10, date_from, date_to, in_universe_candidate,
          source, ingested_at, confidence]
example:
  AAPL | 0000320193 | 2019-06-01 | NULL | True  | iwb_13f_q | 2026-06-19 | 0.95
  WE   | 0001581204 | 2019-09-01 | 2020-04-15 | True | iwb_13f_q | 2026-06-19 | 0.85
  WE   | 0001581204 | 2020-04-16 | NULL | False | sec_delisted | 2026-06-19 | 0.90
```

**중요**: `r1000_pipeline.py:2854 historical_membership_candidates()`가 찾는 path는 `historical_universe_membership.parquet` (no "_candidate" suffix). 이름 정렬:

- `_candidate.parquet` 파일을 만들고
- C4에서 env toggle ON일 때 symlink 또는 환경변수 override로 활성화
- 검증 안 끝난 데이터를 무의식적으로 활성화 못 하게 분리

**SEC rate limit**: 10 req/sec.

**Smoke** (8 test):
1. one quarter 13F 파싱 → ticker list
2. CUSIP → ticker mapping
3. 진입/탈락 date 추정
4. gap detection (한 분기 missing → infer)
5. schema validation
6. rerun idempotency
7. empty data 안전
8. rate limit honored

**Estimated**: 5 days.

### 6.2 PR C2 — PIT ADR/Cycle Scanner

**Branch**: `codex/pit-adr-scanner-20260619`
**File**: `tools/run_pit_universe_scanner.py`

**Logic**: scan_date 기준 (6개월 sliding) ADR/cycle 후보를 그 시점 데이터로 평가.

**Critical**: 모든 mkt_cap, liquidity, sector lookup은 **scan_date 기준 PIT** — 현재 mkt cap 사용 금지.

**Outputs**:
- `data_pit/universe/pit_adr_addendum.parquet`
- `data_pit/universe/pit_cycle_addendum.parquet`

Schema:
```
scan_date, ticker, kind (adr|cycle), mc_at_scan, liq_at_scan, sector_at_scan, source
```

**Smoke** (7 test):
1. 1 scan_date 정확
2. mkt cap PIT (현재 값 안 씀)
3. shares PIT (SEC accepted by scan_date)
4. sector PIT
5. threshold edge case (mc 정확히 $8B)
6. 미상장 ticker skip with reason
7. idempotent rerun

**Estimated**: 4 days.

### 6.3 PR C3 — 13F/Form4 PIT Candidates

**Branch**: `codex/pit-13f-form4-candidates-20260619`
**File**: `tools/run_pit_smart_money_candidates.py`

**Logic**:
- 13F: T-180d ~ T-30d (PIT 제출 지연) 사이 top-7 매니저 신규 진입
- Form4: T-90d cluster insider buy (≥3 distinct insiders AND ≥$5M total)

**Output**: `data_pit/universe/pit_smart_money_candidates.parquet`

Schema:
```
scan_date, ticker, reason_13f_new_position (bool),
reason_form4_cluster (bool),
n_distinct_managers, n_distinct_insiders, total_form4_value_usd, source
```

**기존 도구 재사용**:
- `tools/build_top_manager_discovery_signals.py` (Codex 자신이 만든 것)
- `tools/run_sec_form4_parser.py`

**Smoke** (7 test):
1. new position detection 정확
2. cluster buy threshold (3 insiders, $5M)
3. PIT 30d lag respected (제출 미반영 시점 skip)
4. idempotent rerun
5. ticker tradeable check
6. manager universe alignment
7. empty window safe

**Estimated**: 3 days.

### 6.4 PR C4 — Universe Builder PIT Integration

**Branch**: `codex/universe-pit-integration-20260619`
**Files modified**: `r1000_pipeline.py` `build_universe_monthly` + `load_adr_universe_frame`, `load_cycle_play_universe_frame`.

**핵심 변경**:
- 새 함수 `load_pit_universe_addendum(scan_date: pd.Timestamp)` — C2/C3 outputs 통합
- `build_universe_monthly`의 각 월 loop에서 그 월 scan_date로 universe pool 재계산
- env gate `PHASE_PIT_UNIVERSE_ENABLED` (default OFF) — A/B 후 별도 결정으로 ON

**중요**: env OFF일 때 기존 동작과 완벽 동일 (no regression).

**Smoke** (10 test):
1. env OFF → 기존 universe 결과와 byte-identical
2. env ON → 월별 universe 변화 검출
3. 미래 leakage 0 (어떤 scan_date도 그 이후 데이터 안 봄)
4. ADR PIT 정확 적용
5. cycle PIT 정확 적용
6. env toggle 동작
7. 신규 ticker 진입 추적
8. 탈락 ticker 정확 제외
9. empty PIT data graceful (env OFF로 fallback)
10. 머지 충돌 없음 (기존 키워드 columns 보존)

**Estimated**: 4 days.

### 6.5 PR C5 — Semi-Annual Auto-Schedule Workflow

**Branch**: `codex/universe-rebuild-semiannual-20260619`
**File**: `.github/workflows/universe_pit_rebuild_semiannual.yml`

**Schedule**: `cron: '0 0 1 1,7 *'` (1월 1일 + 7월 1일).

**Job**:
1. `tools/build_pit_r1000_membership.py --refresh`
2. `tools/run_pit_universe_scanner.py --refresh`
3. `tools/run_pit_smart_money_candidates.py --refresh`
4. 변경된 parquet/csv를 새 branch `bot/universe-refresh-<date>`에 commit
5. PR auto-open for human review (production 적용 금지 — review만)

**중요**: live production target 적용 금지. 어디까지나 candidate PR.

**Smoke** (5 test):
1. workflow YAML 유효
2. schedule cron 정확 (`0 0 1 1,7 *`)
3. dry-run mode 가능
4. PR auto-open with `[bot] universe refresh` title
5. PR base = `master`, head = `bot/universe-refresh-<date>`

**Estimated**: 2 days.

### 6.6 Workstream C 정리

| PR | Task | Est | Output 위치 |
|---|---|---|---|
| C1 | Historical R1000 membership ETL | 5d | `data_raw/historical_universe_membership_candidate.parquet` |
| C2 | PIT ADR/cycle scanner | 4d | `data_pit/universe/pit_*_addendum.parquet` |
| C3 | 13F/Form4 PIT candidates | 3d | `data_pit/universe/pit_smart_money_candidates.parquet` |
| C4 | Universe builder PIT integration | 4d | `r1000_pipeline.py` 수정 (env-gated default OFF) |
| C5 | Semi-annual auto-schedule | 2d | `.github/workflows/universe_pit_rebuild_semiannual.yml` |

총 18일. C1-C3 병렬, C4는 C1+C2+C3 출력 의존, C5는 마지막.

---

## 7. Output Schemas (v1 §7 그대로)

§7.1~7.6 동일. **§7.7 Combined Report는 v2에서 삭제** (12 PR 외 추가 작업 금지).

각 도구의 JSON output schema는 v1 plan `9abe721a`의 §7 참조 (변경 없음).

---

## 8. Smoke Test 의무 (v1 §8 그대로)

- 각 PR `tests/<tool_name>_smoke.py` 필수
- `tools/run_pr_validation.py` 등록
- 최소 5-10 test
- 각 test ≤ 10초
- Math 검증 (synthetic known answer)
- Edge case (empty, NaN, single date, mismatched dates)
- Reproducibility (B4 seed)

---

## 9. Sidecar Wiring (v1 §9 그대로)

`tools/run_full_rebuild_sidecars.py:~219` (performance_ledger 다음).

```bash
  # CAGR credibility sidecars — measurement only, no engine mutation.
  python tools/run_cagr_walkforward.py --latest-run outputs --output-dir outputs/cagr_walkforward 2>&1 | tee outputs/full_rebuild_logs/cagr_walkforward.log || true
  python tools/run_factor_attribution.py --latest-run outputs --output-dir outputs/factor_attribution 2>&1 | tee outputs/full_rebuild_logs/factor_attribution.log || true
  python tools/run_cagr_start_date_sensitivity.py --latest-run outputs --output-dir outputs/cagr_start_date_sensitivity 2>&1 | tee outputs/full_rebuild_logs/cagr_start_date_sensitivity.log || true
  python tools/run_cagr_bootstrap_ci.py --latest-run outputs --output-dir outputs/cagr_bootstrap_ci 2>&1 | tee outputs/full_rebuild_logs/cagr_bootstrap_ci.log || true
  python tools/run_cagr_regime_decomposition.py --latest-run outputs --output-dir outputs/cagr_regime_decomposition 2>&1 | tee outputs/full_rebuild_logs/cagr_regime_decomposition.log || true
  if [ "${ENABLE_COST_STRESS:-false}" = "true" ]; then
    python tools/run_cagr_cost_stress.py --latest-run outputs --output-dir outputs/cagr_cost_stress 2>&1 | tee outputs/full_rebuild_logs/cagr_cost_stress.log || true
  fi
```

(B7 통합 report 라인 v2에서 삭제)

---

## 10. Codex 첫 응답 강제 형식 (사용자 버전 그대로)

```
Verification preamble:
  [LOCAL] repo path:                    /<path>/r1000-quant-engine
  [GITHUB] current branch:              <branch>
  [GITHUB] origin/master SHA:           <sha>
  [GITHUB] origin/codex/*-20260619 branch count:   <integer; if > 5 STOP>
  [LOCAL] working tree status:          clean | dirty (list)

Task selected:                          A1 | B1 | B2 | ... | C5  (exactly one)
Branch to create:                       codex/<name>-20260619
Base:                                   master  | codex/...  (justify if not master)

Files expected to change:
  <list with each [LOCAL] path>

Files explicitly forbidden in this PR:
  <list specific to workstream — A forbids selection engine + bull-floor;
   B forbids r1000_pipeline.py etc.; C non-C4 forbids engine modification>

Smoke tests to add:
  tests/<smoke_name>.py with <count> tests
  Math sanity (synthetic data): <Y/N>
  Edge cases (empty/NaN/single): <Y/N>
  Reproducibility (seed): <Y/N if applicable>

Abort conditions:
  - Branch count exceeds 12
  - Diff touches a forbidden file
  - Smoke fails synthetic-data math check
  - schema deviates from §7
  - PR base is not master/justified
```

각 PR 종료 시 status block (v1 §10.2 그대로) + 12 PR 종료 시 end acknowledgment (v1 §13 그대로).

---

## 11. Math 가드 (v1 §11 그대로)

- `compute_cagr_safe()` 헬퍼 `r1000_helpers.py`에 추가, B1-B6 import
- `days / 365.25` 표준
- Sharpe annualize `sqrt(252)`
- Log return: Sharpe, regression, bootstrap
- Simple return: CAGR, factor regression input
- Bootstrap seed: `np.random.default_rng(20260615)`
- FP 비교: `abs(a-b) < 1e-9`

---

## 12. Escalation Triggers (v2 강화)

즉시 중단 + 사용자 보고:

- 같은 날짜 codex 브랜치 5개 초과 (count check)
- 12개 다 만든 후 13번째 시도
- branch 이름이 §0.1 화이트리스트에 없음
- A1 diff가 `r1000_pipeline.py` 또는 `tools/run_alphaops_vnext_policy_replay.py` 포함
- B 어느 PR diff가 selection 엔진 5개 파일 중 하나라도 포함
- C 어느 PR이 `tools/run_broker_ledger_replay.py` 수정
- C4 외 C 어느 PR이 `r1000_pipeline.py` 수정
- B5 cost_stress가 기존 25bps run과 일치 안 함 (≥0.5pp 차이)
- C1 SEC API rate limit 10 req/sec 초과
- `auto_trade_allowed` 또는 `production_activation_allowed` true로 변경 발견
- `PORTFOLIO_GOAL_TARGETS` 변경 발견
- 사용자 "stop" 또는 "잠깐" 메시지

---

## 13. End Acknowledgment (12 PR 완료 후)

```
I read CODEX_IMPLEMENTATION_PLAN_v2 (this prompt) and confirm understanding of:
  - §0 objective: clean 7Y research/A-B baseline, six measurement sidecars, PIT universe
  - §0.1 anti-proliferation: 12 PR exact count, no safety/gate/require-X/proxy branches
  - §0.2 location discipline: [LOCAL] / [GITHUB] / [DRIVE] every command
  - §3 forbidden mutations: no selection engine in B, no broker_replay in any of B,
    no bull-floor promote, no production target change

12 PRs opened (exact count):
  Workstream A (7Y lock):
    A1: <url>  codex/lock-7y-window-20260619
  Workstream B (CAGR credibility, measurement-only):
    B1: <url>  codex/cagr-walkforward-20260619
    B2: <url>  codex/cagr-factor-alpha-20260619
    B3: <url>  codex/cagr-start-date-sensitivity-20260619
    B4: <url>  codex/cagr-bootstrap-ci-20260619
    B5: <url>  codex/cagr-cost-stress-20260619
    B6: <url>  codex/cagr-regime-decomp-20260619
  Workstream C (PIT universe, engine touch in C4 only):
    C1: <url>  codex/pit-r1000-membership-20260619
    C2: <url>  codex/pit-adr-scanner-20260619
    C3: <url>  codex/pit-13f-form4-candidates-20260619
    C4: <url>  codex/universe-pit-integration-20260619
    C5: <url>  codex/universe-rebuild-semiannual-20260619

Total smoke tests added: <N>
Total LOC added: <N>
Branch namespace check: codex/*-20260619 count == 12 ✓
No safety/gate/require-X-safety/proxy8/proxy10 branches created ✓
No bull-floor / no production target / no live trading mutation ✓

Awaiting:
  - ChatGPT Pro review especially on:
      A1 (forbidden file boundary)
      B2 (regression math correctness)
      C4 (universe builder integration regression safety)
  - User merge decisions
  - First full rebuild after merges to validate sidecar wiring
```

🟦 [END OF PROMPT — Codex starts here] 🟦

---

## 사용 방법 (메타-노트, Codex에 붙이지 마세요)

1. `🟦 [PASTE TO CODEX FROM HERE] 🟦` ~ `🟦 [END OF PROMPT — Codex starts here] 🟦` 사이 복사.
2. Codex 첫 응답이 §10 verification preamble로 시작하는지 확인. 안 그러면 reject.
3. 매 PR 완료 시 §10 status block 출력 확인.
4. `codex/*-20260619` namespace 외 브랜치 즉시 escalate.
5. 13번째 PR 시도 시 reject.
6. A1 PR diff에 `tools/run_alphaops_vnext_policy_replay.py` 포함 시 즉시 reject (bull-floor 끼움).
7. B 어느 PR이라도 `r1000_pipeline.py` / `r1000_features.py` / `r1000_signals.py` 수정 시 즉시 reject.

## v1 → v2 변경 요약

| 항목 | v1 | v2 |
|---|---|---|
| Authority 표현 | "공식 SHIP window" | "clean 7Y research/A-B baseline" |
| Proxy 차단 | 8Y만 | 8Y AND 10Y (workflow + config + account_evaluation 셋 다) |
| Bull-floor 처리 | A1 review에 묶임 | A1에서 명시 제외 — 별도 alpha PR |
| Anti-proliferation 위치 | §3 (중간) | §0.1 (첫 줄) + 화이트리스트 정확한 12 브랜치명 |
| 첫 응답 preamble | 일반적 | 사용자 버전 — Files expected/forbidden + Abort conditions |
| Engine 수정 권한 | 분산 | C에서만, C4만 (env-gated default OFF) |
| Total PR | 12 + 1 optional (B7) | 정확히 12 (B7 삭제) |
| `historical_universe_membership.parquet` | "official" | "_candidate.parquet" (검증 안 끝난 데이터 분리) |

---

**End of Codex Implementation Plan v2 — 2026-06-19 KST**

Author: Claude Code. Reviewer: 사용자 정정 반영 (2026-06-19).
Update protocol: 12 PR 모두 머지 후 또는 Workstream C 결과로 universe 변화 측정 후 재작성.
