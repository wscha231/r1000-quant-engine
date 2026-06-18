# Codex Implementation Plan — 7y Lock + Full CAGR Credibility + PIT Universe

> **이 문서는 Codex가 다음 6주간 실행할 구체 설계서입니다.**
> 7년 window 고정 결정 + Full CAGR 신빙성 확보 + PIT universe 재구성.
> 출처 brief: `docs/CODEX_GOAL_SETTING_BRIEF.md`, `docs/CODEX_PROMPT_48H_ACTION_PACK.md`.
> 모호함 0이 목적. 각 PR이 정확히 무엇을 만들고 어떤 검증을 통과해야 하는지 schema까지 박아둠.

---

## 🟦 [PASTE TO CODEX FROM HERE] 🟦

Codex, 사용자가 다음 결정을 했다:

1. **백테스트 window를 7년으로 고정** (8년 proxy 확장 중단).
2. **Full CAGR의 신빙성을 측정 도구 6개로 입증** (walk-forward / α-β / start-date / bootstrap / cost stress / regime).
3. **Universe를 PIT-clean으로 재구성** (survivorship bias 제거, 6개월 재선정 + 자동 스케줄).

너의 임무는 **이 3개 workstream을 무오류로 구현**하는 것이다. 지난 2일 동안 너는 73개 브랜치를 만들었고 61개가 orphan이 됐다. 이번엔 그러지 마라. **§3 anti-proliferation 규칙을 위반하면 작업 중단.**

---

## 0. Location Discipline (Action Pack §0과 동일, 강제)

| Tag | 의미 |
|---|---|
| `[LOCAL]` | 너의 clone working tree (`/home/.../r1000-quant-engine/` 등) |
| `[GITHUB]` | `github.com/wscha231/r1000-quant-engine` 원격 (truth source) |
| `[DRIVE]` | Google Drive mirror (read-only) |

**모든 명령에 위치 tag.** 예외 없음. 위반 시 작업 reject.

---

## 1. 결정 컨텍스트 (왜 이걸 하는가)

### 1.1 검증된 사실

| 사실 | 출처 |
|---|---|
| Bull-floor A/B 검증 — Main IS +1.45pp, Conc IS +1.12pp, Main Tier-1 통과 | `[GITHUB]` `origin/master:cloud_results/performance_ledger/ledger.jsonl` row 4 (run 27516185696) |
| 그러나 bull-floor가 master에서 default OFF | `tools/run_alphaops_vnext_policy_replay.py:2712` `default=False` |
| 최신 run IS-CAGR이 22.90→22.36 퇴보 | ledger row 5 (run 27614583121) |
| 8년 확장 시도 readiness probe → 6 hard blockers, `pit_universe_label` 가 핵심 | `cloud_results/full_rebuild/failed_runs/27614583121.../eight_year_backtest_readiness/summary.json` |
| ADR/cycle YAML 마지막 손큐레이션 2026-05 | `git log -1 adr_universe.yaml cycle_play_universe.yaml` |
| Historical universe membership file은 코드 path는 있지만 **파일 없음** | `r1000_pipeline.py:2854-2882` + `find data_raw/historical_*` → 빈 결과 |
| Form4/13F는 score에만 들어가고 universe 결정에는 안 들어감 | `grep "13f.*universe\|form4.*universe" r1000_pipeline.py` → 0 hits |
| Full CAGR 44.43% (Conc) = IS 22.41% × 5.07y + OOS 123.26% × 1.95y 의 기하평균 | `cloud_results/.../broker_replay/concentrated/metrics.json` windows |

### 1.2 결정

- ❌ **8년 proxy 확장 작업 중단**. `pit_universe_label` 없이 8년 확장 = survivorship-biased headline 양산 = F4 함정 재진입.
- ✅ **7년 (2019-06 ~ 2026-06)을 공식 SHIP window로 확정**.
- ✅ **Full CAGR의 신빙성을 6개 측정 도구로 입증** (강조: 도구는 **측정**이지 **개선**이 아님 — 결과가 좋게 안 나올 수도 있고, 그 진실이 가치).
- ✅ **Universe를 PIT-clean으로 재구성** — 이게 Full CAGR 신빙성의 가장 큰 단일 lever.

---

## 2. Workstream 3개 (총 12 PR, 6주)

### 2.1 Workstream A — 7년 Lock + 8y proxy 중단 (1 PR, 1일)

목적: 8년 확장 작업이 다시 시작되는 걸 코드로 차단.

### 2.2 Workstream B — Full CAGR Credibility 도구 6개 (6 PR, 2주)

목적: Full CAGR 44%가 진짜 알파인지 leveraged QQQ인지 데이터로 답.

### 2.3 Workstream C — PIT Universe 재구성 (5 PR, 3-4주)

목적: 우주에 주입된 survivorship bias 제거. 6개월 자동 재선정.

---

## 3. Anti-Proliferation 강제 규칙 (위반 시 즉시 중단)

### 3.1 절대 금지

| 금지 | 검출 |
|---|---|
| **브랜치 양산** (같은 PR을 require-X-safety, require-Y-safety로 쪼개기) | 새 브랜치 만들기 전 `git for-each-ref refs/remotes/origin/codex/ --format='%(refname:short)' \| grep '20260619'` 으로 같은 날짜 이미 만든 브랜치 수 확인. **5개 초과면 STOP.** |
| **task 하나에 2 PR 이상** | 각 §4, §5, §6의 PR은 **정확히 1개** 본 PR. squash merge 가능한 sub-commit은 OK, 별도 PR은 X. |
| **자기 PR 머지** | `gh pr merge` 금지. 사용자만. |
| **`master` 직접 push** | branch-protect 있지만 실수 방지. |
| **selection 엔진(`r1000_pipeline.py`, `r1000_features.py`, `r1000_candidate_lanes.py`) 수정 — workstream B에서** | workstream B는 측정 도구만. 엔진 수정은 별도 결정 후 별도 PR. |
| **smoke 없이 commit** | 각 새 tool은 `tests/<name>_smoke.py` 필수. `tools/run_pr_validation.py`에 등록. |
| **schema 자유 변경** | §7 schema 정확히 따라야. 필드명·타입·단위 변경은 사용자 승인. |

### 3.2 의무

- **task 당 1 branch 1 PR**, branch name `codex/<workstream>-<task>-20260619` 형식.
- **각 PR description에**: 어느 workstream/task인지, success criteria가 §어디인지, smoke 결과 표시.
- **6주 끝에 12 PR이 정확한 수** — 더 만들면 작업 거부.

---

## 4. Workstream A — 7년 Lock + 8y proxy 중단 (1 PR)

### 4.1 PR A1 — `codex/lock-7y-window-20260619`

**목적**: 8년 확장 작업이 무의식적으로 재개되지 못하게 코드 잠금.

**범위**:
- `r1000_config.py`에 새 상수 추가:
  ```python
  # 7년 lock — 2026-06-15 user 결정. 8년 확장은 pit_universe_label
  # blocker가 풀리기 전까지 시도 금지 (proxy = survivorship bias).
  OFFICIAL_BACKTEST_WINDOW_YEARS = 7.0
  OFFICIAL_BACKTEST_START_DATE = "2019-06-03"
  OFFICIAL_BACKTEST_END_DATE_POLICY = "latest_close"  # 매번 종가 기준
  EIGHT_YEAR_EXTENSION_BLOCKED = True
  EIGHT_YEAR_EXTENSION_BLOCKER_REASON = "pit_universe_label_missing"
  ```
- `tools/run_account_evaluation.py`에 hard-fail 추가:
  ```python
  # broker_replay metrics가 7.05년 초과 + survivorship-clean=false면 fail
  if window_years > 7.05 and not metrics.get("pit_universe_label_clean"):
      raise RuntimeError(
          f"window_years={window_years:.2f} > 7.05 with pit_universe_label_clean=false: "
          "8-year extension blocked per OFFICIAL_BACKTEST_WINDOW_YEARS lock. "
          "Resolve pit_universe_label blocker (Workstream C) first."
      )
  ```
- `tools/run_eight_year_backtest_readiness.py` (Codex가 이미 만든 것)의 hard_blocker_count 출력에 명시:
  ```python
  summary["lock_status"] = "OFFICIAL_7Y_LOCKED_UNTIL_PIT_UNIVERSE_CLEAN"
  ```
- **`backtest_years=8` 입력으로 `full_rebuild_manual.yml` dispatch 시 워크플로 자체가 거부**: `.github/workflows/full_rebuild_manual.yml` 의 backtest_years input validation 단계 추가, 8 값 들어오면 워크플로 fail.

**Smoke**: `tests/seven_year_lock_smoke.py` (8 test):
1. `OFFICIAL_BACKTEST_WINDOW_YEARS == 7.0`
2. window > 7.05 + clean=false 시 account_evaluation raise
3. window ≤ 7.05 시 raise 없음
4. window > 7.05 + clean=true 시 raise 없음 (미래 unlock 대비)
5. `EIGHT_YEAR_EXTENSION_BLOCKED is True`
6. eight_year_readiness summary에 lock_status 키 있음
7. backtest_years=8 dispatch validation 거부 (workflow YAML 파싱)
8. import 가능

**Success criteria**:
- ✅ `[GITHUB]` PR open, smoke 8/8 pass
- ✅ ChatGPT Pro review, "this prevents accidental proxy extension" 확인
- ✅ User 머지

**Estimated**: 1 day.

---

## 5. Workstream B — Full CAGR Credibility 도구 6개 (6 PR)

### 5.0 공통 원칙

- 모든 도구는 **새 sidecar** (`tools/run_<name>.py`). 기존 `broker_replay`, `account_evaluation` 등 **수정 금지**.
- 모든 도구는 **input = `outputs/broker_replay/<kind>/{metrics.json, equity_curve.csv, trades.csv}`**. 신규 입력 데이터 없음.
- 모든 도구는 **output = `outputs/<tool_name>/<kind>_summary.{json,md}`**.
- 모든 도구는 `run_full_rebuild_sidecars.py`의 `run_performance_ledger.py` **다음**에 wire. 위치: `tools/run_full_rebuild_sidecars.py:~219` 다음.
- 모든 도구는 **non-fatal** (`|| true`). 실패해도 main pipeline 안 막음.
- 모든 도구는 **per-portfolio** (`main`, `concentrated` 둘 다).

### 5.1 PR B1 — Walk-forward OOS CAGR (`codex/cagr-walkforward-20260619`)

**목적**: 단일 1.95년 OOS 대신 4개 1년 rolling OOS의 평균을 측정. F4 leakage 검출.

**파일**: `tools/run_cagr_walkforward.py`.

**Math**:
```
equity_curve.csv → 일별 (date, equity_usd, cash_weight)

Rolling test windows (training은 retrain 없이 평가 단순화 — 즉 "rolling
sample CAGR" not "walk-forward retrain CAGR"; 후자는 r1000_pipeline 재실행
필요 = 별도 작업):

window_1: 2023-01-01 → 2023-12-31  (test on 2023)
window_2: 2024-01-01 → 2024-12-31  (test on 2024)
window_3: 2025-01-01 → 2025-12-31  (test on 2025)
window_4: 2026-01-01 → end_date    (partial 2026)

각 window:
  start_eq = equity at window start
  end_eq = equity at window end (or last available)
  days = (end - start).days
  years = days / 365.25
  CAGR_i = (end_eq / start_eq)^(1/years) - 1
  MDD_i = min(equity / cummax(equity) - 1)
  Sharpe_i = mean(daily_log_returns) / std(daily_log_returns) * sqrt(252)

walk_forward_cagr_avg = mean(CAGR_1 ... CAGR_4)   # 산술평균
walk_forward_cagr_geomean = (prod(1+CAGR_i))^(1/4) - 1  # 기하평균

Report:
  full_cagr (참조 only)
  is_cagr  (참조 only)
  oos_single_window_cagr (현재 single 1.95y OOS)
  walk_forward_cagr_avg  ← 핵심 지표
  walk_forward_cagr_geomean
  per_window_cagr: [...]  (4개)
  inflation_indicator = oos_single_window_cagr / walk_forward_cagr_avg
    → 1.0 이면 single OOS는 평균과 일치 (정직)
    → 2.0+ 이면 single OOS가 평균의 2배 (lottery)
```

**경고**: 이 도구는 **모델 retrain을 하지 않는다**. 같은 학습된 모델의 equity_curve를 시간 구간만 나눠 측정. 진짜 walk-forward retrain은 r1000_pipeline 재실행 필요 (별도 작업, 본 PR 범위 밖).

**Output schema**: §7.1 참조.

**Smoke**: `tests/cagr_walkforward_smoke.py` (6 test):
1. 4 window 정확히 식별
2. CAGR 계산 수식 정확 (known curve test)
3. 산술평균 + 기하평균 수식 정확
4. inflation_indicator = single_OOS / wf_avg
5. equity_curve가 partial year 끝나면 last available date 사용
6. empty curve → graceful "insufficient_data" status

**Wire**: `run_full_rebuild_sidecars.py:219` (performance_ledger 다음).

**Success**: `[GITHUB]` PR open, smoke 6/6, ChatGPT Pro review, retrofit run 27516185696 결과 출력 확인.

**Estimated**: 2 days.

### 5.2 PR B2 — Factor/Alpha Decomposition (`codex/cagr-factor-alpha-20260619`)

**목적**: 44% Full CAGR이 α인지 β인지 회귀로 분해.

**파일**: `tools/run_factor_attribution.py`.

**Math**:
```
inputs:
  equity_curve.csv (일별 portfolio equity)
  yfinance daily adj close: SPY, QQQ, SMH, IWM, IWF, IWD, GLD, TLT
  (factor proxies — 무료 + 안정적)

step 1: portfolio_daily_return = equity[t]/equity[t-1] - 1
step 2: factor_daily_returns = same for each factor proxy
step 3: align dates (drop NaN)

regression:
  r_portfolio = α + β1*r_SPY + β2*(r_QQQ - r_SPY) + β3*(r_SMH - r_QQQ) +
                β4*(r_IWM - r_SPY) + β5*(r_IWF - r_IWD) + β6*r_GLD + β7*r_TLT + ε

  factors:
    r_SPY        : market
    r_QQQ-r_SPY  : large-cap growth tilt
    r_SMH-r_QQQ  : semis tilt
    r_IWM-r_SPY  : small-cap tilt
    r_IWF-r_IWD  : growth vs value
    r_GLD        : gold
    r_TLT        : long bonds

annualize:
  α_annual = α * 252
  β_t-stats (use statsmodels OLS or numpy lstsq + se)
  R²

output:
  alpha_annualized_pct
  alpha_tstat
  betas: { spy: ..., qqq_minus_spy: ..., ... }
  r_squared
  alpha_share_of_full_cagr = α_annual / full_cagr   ← 핵심
    예: full 44.43%, α 3%, share = 0.067 (전체 CAGR의 7% 만 알파)
  beta_share_of_full_cagr = (full_cagr - α_annual) / full_cagr
```

**Dependency**: `statsmodels` or numpy lstsq. `statsmodels` 있으면 그걸로, 없으면 numpy로 OLS + manual se 계산.

**Smoke**: `tests/factor_attribution_smoke.py` (7 test):
1. 합성 데이터 (α=10%, β_SPY=1.0)로 회귀 → α 9-11%, β 0.95-1.05 복원
2. perfect SPY mirror → α≈0, β_SPY≈1, R²≈1
3. random walk → α≈0, R²≈0, no false positive
4. annualized: 일별 α * 252
5. t-stat 계산 정확
6. NaN 처리 (factor data 일부 missing)
7. empty curve → "insufficient_data"

**Wire**: B1 다음.

**Estimated**: 3 days (회귀 + 팩터 fetch + smoke).

### 5.3 PR B3 — Start-Date Sensitivity (`codex/cagr-start-date-sensitivity-20260619`)

**파일**: `tools/run_cagr_start_date_sensitivity.py`.

**Math**:
```
start_dates = [
  "2019-06-03",  # current default
  "2019-12-02",
  "2020-03-23",  # COVID bottom
  "2020-06-01",
  "2021-01-04",  # high growth period
  "2021-06-01",
  "2022-01-03",  # pre-bear
]

for each start_date sd:
  if sd < equity_curve.start: skip
  segment = equity_curve[equity_curve.date >= sd]
  start_eq = segment.equity_usd.iloc[0]
  end_eq = segment.equity_usd.iloc[-1]
  years = (segment.date.iloc[-1] - segment.date.iloc[0]).days / 365.25
  CAGR_sd = (end_eq/start_eq)^(1/years) - 1

output:
  per_start_date: [{ sd: "2019-06-03", years: 7.03, cagr: 0.4443 }, ...]
  cagr_range_pp = (max - min) * 100   # 변동 폭
  cagr_median = median of CAGRs
  start_date_robustness_score:
    if range_pp < 5: "ROBUST"
    elif range_pp < 15: "MODERATE"
    else: "FRAGILE"
```

**Smoke**: 5 test (각 분기에서 known CAGR, edge case start_date == end_date, future date skip, etc).

**Estimated**: 1 day.

### 5.4 PR B4 — Block Bootstrap CI (`codex/cagr-bootstrap-ci-20260619`)

**파일**: `tools/run_cagr_bootstrap_ci.py`.

**Math**:
```
inputs:
  equity_curve.csv → daily log returns: r_t = log(eq[t]/eq[t-1])

block bootstrap:
  block_size = 20 (트레이딩일 ~1개월, monthly cycle 보존)
  n_resamples = 1000
  for i in 1..1000:
    # 길이 7y * 252 일 ≈ 1770 트레이딩일
    # 1770 / 20 = 88.5 blocks 필요. 정수 89 블록 sample with replacement.
    blocks = random.choices(all_blocks, k=89)
    resampled_returns = concatenate(blocks)
    cumulative_growth = exp(sum(resampled_returns))
    CAGR_i = cumulative_growth^(1/7.03) - 1

  → distribution of 1000 CAGRs

output:
  point_estimate = full_cagr from broker_replay (참조)
  bootstrap_median
  bootstrap_p5 (5th percentile)
  bootstrap_p95 (95th percentile)
  bootstrap_p50 (median)
  ci_95_width_pp = (p95 - p5) * 100
  credibility_score:
    if ci_95_width_pp < 10: "TIGHT"
    elif ci_95_width_pp < 25: "MODERATE"
    else: "LOOSE"
```

**Random seed**: `np.random.default_rng(20260615)` — deterministic for reproducibility.

**Smoke**: 6 test (known curve → expected CI, seed reproducibility, block size validation, NaN handling, empty curve, edge case n_blocks).

**Estimated**: 1 day.

### 5.5 PR B5 — Cost Stress Test (`codex/cagr-cost-stress-20260619`)

**주의**: 이 도구는 다른 도구와 다름 — `broker_replay`를 **재실행**한다. 비용 높음.

**파일**: `tools/run_cagr_cost_stress.py`.

**Logic**:
```
cost_levels_bps = [25, 50, 75, 100, 150]  # roundtrip

for cost_bps in cost_levels_bps:
  output_dir = f"outputs/cost_stress/{cost_bps}bps/{kind}"
  subprocess.run([
    "python", "tools/run_broker_ledger_replay.py",
    "--target-book", target_book,
    "--price-cache", "cache_prices",
    "--portfolio-kind", kind,
    "--output-dir", output_dir,
    "--fill-mode", "next_close",
    "--cost-bps", str(cost_bps),
    "--max-fill-lag-days", "7",
  ])
  result = read_json(f"{output_dir}/metrics.json")
  collect(cost_bps, result.cagr, result.max_dd, result.sharpe)

# linear sensitivity
slope_pp_per_bp = (cagr_at_25 - cagr_at_150) / (150 - 25) * 100  # 음수 (cost 오르면 CAGR 떨어짐)

cost_robustness_score:
  if cagr_at_100 > 0.25: "ROBUST"   # 100bps에서도 25% CAGR
  elif cagr_at_50 > 0.30: "MODERATE"
  else: "FRAGILE"
```

**Output schema**: §7.5.

**Smoke**: 5 test (각 cost level 정확 호출, sensitivity 계산, robustness score threshold, broker_replay 실패 graceful, output dir clean).

**경고**: `[LOCAL]` 테스트 시 broker_replay 5번 = 비싸다. Smoke는 `unittest.mock`으로 broker_replay 호출을 mock하고 metrics.json만 fake.

**Wire**: 비용 때문에 default OFF (`--skip-cost-stress`). `full_rebuild_manual.yml` workflow input `enable_cost_stress=false` default. 사용자가 명시적으로 켜야.

**Estimated**: 2 days.

### 5.6 PR B6 — Regime Decomposition (`codex/cagr-regime-decomp-20260619`)

**파일**: `tools/run_cagr_regime_decomposition.py`.

**Math**:
```
inputs:
  equity_curve.csv (daily)
  target book daily-resolved regime_state column
    (현재는 monthly. 일별 매핑: 그 월의 regime_state를 그 월의 모든 거래일에 적용)

per_regime aggregation:
  for each regime in {strong_bull, bull, neutral, bear, deep_bear, unknown}:
    days_in_regime = count
    if days_in_regime == 0: skip
    daily_returns_in_regime = [...]
    mean_daily_return = mean(...)
    std_daily_return = std(...)
    annualized_return = mean_daily * 252
    annualized_vol = std_daily * sqrt(252)
    sharpe_in_regime = annualized_return / annualized_vol (if vol > 0)
    contribution_to_full_cagr_pp =
      mean_daily_return * days_in_regime / total_days * 252 * 100

  → table with 1 row per regime present

output:
  per_regime: { strong_bull: {...}, bull: {...}, ... }
  cagr_concentration:
    top_regime_share = max(contribution_pp) / sum(positive_contributions_pp)
    if top_regime_share > 0.7: "DIRECTIONAL"    # 한 regime에 의존
    elif top_regime_share > 0.5: "TILTED"
    else: "BALANCED"
  bull_only_cagr_pct
  neutral_only_cagr_pct
  bear_only_cagr_pct
```

**Smoke**: 6 test (3 regime 균등 분포 → balanced, bull 90% → directional, regime 매핑 정확, missing regime column graceful, NaN return 처리, 0 days regime skip).

**Estimated**: 1 day.

### 5.7 Workstream B 총정리

PR | Tool | LOC ≈ | Est | Output
---|---|---|---|---
B1 | walkforward CAGR | 250 | 2d | rolling 4-window CAGR + inflation indicator
B2 | factor attribution | 350 | 3d | α + β + R² + α share of CAGR
B3 | start-date sensitivity | 150 | 1d | 7 start dates × CAGR
B4 | bootstrap CI | 200 | 1d | 95% CI + width + credibility score
B5 | cost stress | 250 | 2d | 5 cost levels × CAGR + slope + robustness
B6 | regime decomposition | 200 | 1d | per-regime CAGR + concentration score

**총 10일.** 사이드카 추가로 다음 full rebuild가 자동으로 6개 보고서 생성. 최종 보고서 (§5.8) 통합.

### 5.8 (선택) PR B7 — Combined Credibility Report

목적: B1-B6 출력을 한 페이지 markdown으로 통합.

**파일**: `tools/run_cagr_credibility_report.py`.

읽기: 6 sidecar의 `summary.json` 모두 → 한 표로:

```
# CAGR Credibility Report — <portfolio>

Headline:    44.43% over 7.03y (broker_ledger_next_close, 25bps)

Walk-forward OOS:    avg X% / geomean Y% / inflation_indicator Z
Factor decomposition: α A%/yr, β_SPY B, R² C, α-share-of-CAGR D%
Start-date robust:    range pp E, robustness F
Bootstrap 95% CI:     [G%, H%], width pp I, credibility J
Cost stress:          25bps=X, 100bps=Y, slope -Z pp/bp, robustness K
Regime breakdown:     bull L%/yr, neutral M%/yr, bear N%/yr, concentration O

Overall credibility verdict:
  if (α_share > 0.30 AND wf_inflation < 1.5 AND start_robust != FRAGILE
      AND cost_robust != FRAGILE AND ci_width < 25):
    "HIGH"
  elif (α_share > 0.15 AND wf_inflation < 2.0):
    "MODERATE"
  else:
    "LOW — Full CAGR likely inflated by OOS lottery + market beta"
```

**Estimated**: 1 day.

---

## 6. Workstream C — PIT Universe 재구성 (5 PR)

이게 사용자가 직접 제안한 핵심 작업. F4 (universe survivorship)의 가장 큰 lever.

### 6.0 5-stage roadmap

```
C1 → Historical R1000 membership data (B 옵션: SEC + iShares 13F 복원)
C2 → PIT ADR/cycle scanner (6개월 sliding window)
C3 → 13F/Form4 candidate inclusion
C4 → Universe builder PIT integration
C5 → Auto-schedule workflow
```

### 6.1 PR C1 — Historical R1000 membership ETL (`codex/pit-r1000-membership-20260619`)

**파일**: `tools/build_pit_r1000_membership.py`.

**Data source 전략 (B 옵션)**:
- SEC EDGAR에서 iShares R1000 ETF (IWB)의 분기 13F filings 다운로드
- 각 분기 IWB 보유 = 그 분기 시점 R1000 근사 (정밀도 90%)
- 추가: SEC company submissions API로 historical ticker symbol 변경, 상장폐지 일자 확보
- Russell index annual reconstitution (June 매년)이 핵심 — 그 시점을 anchor로

**Output**:
- `data_raw/historical_universe_membership.parquet` schema:
  ```
  columns: [ticker, cik10, date_from, date_to, in_universe, source, ingested_at]
  rows: one per (ticker, membership-interval)
  example: AAPL | 0000320193 | 2019-06-01 | NULL | True  | iwb_13f_q | 2026-06-15
           WE   | 0001581204 | 2019-09-01 | 2020-04-15 | True | iwb_13f_q | ...
           WE   | 0001581204 | 2020-04-16 | NULL | False | delisted | ...
  ```

**Logic**:
1. SEC EDGAR API로 iShares Trust CIK (`0001100663`) submissions
2. 13F-HR filings 분기별 다운로드 (2018-Q1부터)
3. 각 13F → 보유 ticker 추출 (CUSIP → ticker mapping via existing `tools/build_sec_13f_cusip_ticker_map.py`)
4. 보유 → (ticker, period_end_date) tuple
5. ticker 별로 first_seen, last_seen, gaps 분석 → 진입/탈락 date 추정
6. delisted/ticker change는 SEC submissions API의 historical filings 패턴으로 보강

**API rate limit**: SEC 10 req/sec. 분기 30개 × 600 holdings ≈ 18000 records, fetch 10분.

**Smoke**: 8 test (one quarter 13F 파싱, CUSIP→ticker, ticker 진입/탈락 추정, gap detection, schema validation, ingestion timestamp, rerun idempotency, 빈 data 안전).

**Output 위치**: `data_raw/historical_universe_membership.parquet` — `r1000_pipeline.py:2854 historical_membership_candidates()`가 이미 이 path를 찾도록 코딩됨. 파일 만들면 자동 활성화.

**Estimated**: 5 days (가장 무거운 작업, SEC API + CUSIP 매핑 + gap analysis).

### 6.2 PR C2 — PIT ADR/Cycle scanner (`codex/pit-adr-scanner-20260619`)

**파일**: `tools/run_pit_universe_scanner.py`.

**Logic**:
```
scan_date (sliding 6-month):
  for each date in [2019-06, 2019-12, 2020-06, 2020-12, ..., 2026-06]:

    # ADR candidates
    adr_candidates = []
    for ticker in adr_universe_yaml + ADR_screening_pool:
      if listed_at(ticker) <= scan_date:
        mc = mkt_cap_at(ticker, scan_date)
        liq = liquidity_at(ticker, scan_date, lookback=90d)
        if mc >= 8e9 and liq >= 50e6:
          adr_candidates.append({"ticker": ticker, "scan_date": scan_date,
                                 "mc_at_scan": mc, "liq_at_scan": liq})

    # Cycle play candidates
    cycle_candidates = []
    for ticker in cycle_play_universe_yaml + sector_screening_pool:
      if listed_at(ticker) <= scan_date:
        mc = mkt_cap_at(ticker, scan_date)
        liq = liquidity_at(ticker, scan_date, lookback=90d)
        sector = sector_at(ticker, scan_date)
        if 0.3e9 <= mc <= 30e9 and liq >= 10e6 and sector in CYCLE_SECTORS:
          cycle_candidates.append(...)

  # Emit per-scan-date PIT universe addendum
  write to: data_pit/universe/pit_adr_addendum.parquet
            data_pit/universe/pit_cycle_addendum.parquet

  schema: scan_date, ticker, kind (adr|cycle), mc_at_scan, liq_at_scan, source
```

**Critical**: `mkt_cap_at(ticker, scan_date)` — 그 시점 가격 × 그 시점 shares outstanding 사용. shares는 SEC 10-K/10-Q accepted-by-scan_date에서. **현재 shares 사용 금지** (future leakage).

**Smoke**: 7 test (1개 scan_date 정확, 가격 PIT, shares PIT, sector PIT, threshold edge case, 미상장 ticker skip, idempotent rerun).

**Estimated**: 4 days.

### 6.3 PR C3 — 13F/Form4 candidate inclusion (`codex/pit-13f-form4-candidates-20260619`)

**파일**: `tools/run_pit_smart_money_candidates.py`.

**Logic**:
```
for each scan_date in 6-month grid:
  # 13F top-7 manager new positions
  manager_universe = top_7_managers_active_at(scan_date)  # 기존 PIT manager universe
  new_positions = []
  for mgr in manager_universe:
    holdings_t_minus_180 = mgr_holdings_at(mgr, scan_date - 180d)
    holdings_t_minus_30 = mgr_holdings_at(mgr, scan_date - 30d)  # 30일 PIT lag (제출 지연)
    diff_tickers = set(holdings_t_minus_30) - set(holdings_t_minus_180)
    new_positions.extend(diff_tickers)

  # Form4 cluster insider buy (T-90d ~ T-30d)
  cluster_buys = []
  for ticker in form4_filings_window(scan_date - 90d, scan_date - 30d):
    distinct_insiders_buying = count_distinct_insider_purchases(ticker, window)
    total_value_usd = sum(net_buy_value)
    if distinct_insiders_buying >= 3 and total_value_usd >= 5e6:
      cluster_buys.append(ticker)

  candidates = union(new_positions, cluster_buys)
  filter: ticker tradeable at scan_date (listed, liquid)

  write to: data_pit/universe/pit_smart_money_candidates.parquet
  schema: scan_date, ticker, reason_13f_new_position, reason_form4_cluster,
          n_distinct_managers, n_distinct_insiders, total_form4_value_usd, source
```

**기존 도구 재사용**:
- `tools/build_top_manager_discovery_signals.py` — top-7 manager universe + holdings (Codex 자신이 이전에 만든 것)
- `tools/run_sec_form4_parser.py` — Form4 매수 데이터

**Smoke**: 7 test (new position detection 정확, cluster buy threshold, PIT lag respected, idempotent, ticker tradeable check, manager universe alignment, empty window safe).

**Estimated**: 3 days.

### 6.4 PR C4 — Universe builder PIT integration (`codex/universe-pit-integration-20260619`)

**파일 수정**: `r1000_pipeline.py:7360 build_universe_monthly` + `:2240-3100` adr/cycle 로더.

**핵심 변경**:
- `load_adr_universe_frame()` 와 `load_cycle_play_universe_frame()` 를 PIT-aware로 전환:
  ```python
  def load_adr_universe_frame_pit(scan_date: pd.Timestamp) -> pd.DataFrame:
      pit = pd.read_parquet("data_pit/universe/pit_adr_addendum.parquet")
      return pit[pit.scan_date <= scan_date].sort_values("scan_date").drop_duplicates("ticker", keep="last")
  ```
- 또는 더 단순: `apply_historical_membership_filter` 가 자동으로 PIT 처리해주므로 ADR/cycle도 같은 membership table에 통합.
- `build_universe_monthly` 의 각 월 loop에서 그 월의 scan_date로 universe pool 재계산.

**중요**: 기존 `build_universe_monthly` 가 매월 새로 universe pool 만들지 않음. 이걸 바꿔야 함.

**Backwards compatibility**: env toggle `PHASE_PIT_UNIVERSE_ENABLED` (default OFF 처음엔). A/B 측정 후 default ON 결정.

**Smoke**: 10 test (월별 universe 변화 검출, 미래 leakage 0, ADR/cycle PIT 정확 적용, env toggle 동작, 기존 동작 보존 시 결과 동일, 신규 ticker 진입/탈락 추적, empty pit data graceful, 머지 충돌 없음 etc).

**Estimated**: 4 days.

### 6.5 PR C5 — Auto-schedule workflow (`codex/universe-rebuild-quarterly-20260619`)

**파일 신규**: `.github/workflows/universe_pit_rebuild_quarterly.yml`.

**Schedule**: `cron: '0 0 1 1,7 *'` (매 6개월: 1월 1일 + 7월 1일).

**Job**:
1. `tools/build_pit_r1000_membership.py --refresh` (지난 6개월 신규 13F 반영)
2. `tools/run_pit_universe_scanner.py --refresh` (최신 6개월 scan_date 추가)
3. `tools/run_pit_smart_money_candidates.py --refresh`
4. Commit changes:
   - `data_raw/historical_universe_membership.parquet`
   - `data_pit/universe/pit_adr_addendum.parquet`
   - `data_pit/universe/pit_cycle_addendum.parquet`
   - `data_pit/universe/pit_smart_money_candidates.parquet`
5. Open PR `bot/universe-refresh-<date>` for human review

**Smoke**: 5 test (workflow YAML 유효, schedule 정확, commit gating, PR auto-open, dry-run mode).

**Estimated**: 2 days.

### 6.6 Workstream C 총정리

PR | Task | Est | Days
---|---|---|---
C1 | Historical R1000 membership ETL | 5d
C2 | PIT ADR/cycle scanner | 4d
C3 | 13F/Form4 PIT candidates | 3d
C4 | Universe builder PIT integration | 4d
C5 | Auto-schedule workflow | 2d

**총 18일 (~3.5주).** Workstream B와 병렬 가능.

---

## 7. 정확한 Output Schemas

### 7.1 Walk-forward CAGR (B1)

```json
{
  "schema_version": "cagr-walkforward-v1",
  "portfolio": "concentrated",
  "input_window": { "start": "2019-06-03", "end": "2026-06-12", "years": 7.03 },
  "rolling_windows": [
    { "label": "2023", "start": "2023-01-03", "end": "2023-12-29", "years": 0.99, "cagr": 0.123, "max_dd": -0.14, "sharpe": 0.82 },
    { "label": "2024", "start": "2024-01-02", "end": "2024-12-31", "years": 1.00, "cagr": 0.847, "max_dd": -0.18, "sharpe": 2.14 },
    { "label": "2025", "start": "2025-01-02", "end": "2025-12-31", "years": 1.00, "cagr": 0.961, "max_dd": -0.23, "sharpe": 2.38 },
    { "label": "2026_partial", "start": "2026-01-02", "end": "2026-06-12", "years": 0.44, "cagr": 0.881, "max_dd": -0.15, "sharpe": 1.92 }
  ],
  "walk_forward_cagr_avg": 0.703,
  "walk_forward_cagr_geomean": 0.685,
  "oos_single_window_cagr": 1.233,
  "inflation_indicator": 1.75,
  "verdict": "single_oos_inflated_vs_rolling_avg",
  "generated_at_utc": "2026-06-19T03:00:00Z"
}
```

### 7.2 Factor attribution (B2)

```json
{
  "schema_version": "factor-attribution-v1",
  "portfolio": "concentrated",
  "regression_window": { "start": "2019-06-03", "end": "2026-06-12", "n_days": 1768 },
  "alpha_annualized_pct": 3.21,
  "alpha_tstat": 1.42,
  "alpha_significant_95pct": false,
  "betas": {
    "spy": 1.18,
    "qqq_minus_spy": 0.42,
    "smh_minus_qqq": 0.31,
    "iwm_minus_spy": -0.08,
    "iwf_minus_iwd": 0.19,
    "gld": 0.03,
    "tlt": -0.02
  },
  "r_squared": 0.81,
  "full_cagr_decomposition": {
    "full_cagr_pct": 44.43,
    "alpha_share_pct": 7.2,
    "beta_share_pct": 92.8,
    "interpretation": "leveraged_market_with_tech_tilt"
  },
  "verdict": "LOW_ALPHA_HIGH_BETA",
  "generated_at_utc": "..."
}
```

### 7.3 Start-date sensitivity (B3)

```json
{
  "schema_version": "cagr-start-date-sensitivity-v1",
  "portfolio": "concentrated",
  "per_start_date": [
    { "start": "2019-06-03", "years": 7.03, "cagr": 0.4443 },
    { "start": "2019-12-02", "years": 6.53, "cagr": 0.4012 },
    { "start": "2020-03-23", "years": 6.22, "cagr": 0.5841 },
    { "start": "2020-06-01", "years": 6.03, "cagr": 0.4621 },
    { "start": "2021-01-04", "years": 5.44, "cagr": 0.2283 },
    { "start": "2021-06-01", "years": 5.03, "cagr": 0.2105 },
    { "start": "2022-01-03", "years": 4.44, "cagr": 0.1751 }
  ],
  "cagr_min_pct": 17.51,
  "cagr_max_pct": 58.41,
  "cagr_median_pct": 40.12,
  "cagr_range_pp": 40.9,
  "robustness_score": "FRAGILE",
  "verdict": "Highly start-date dependent; avoiding 2021 peak adds ~25pp.",
  "generated_at_utc": "..."
}
```

### 7.4 Bootstrap CI (B4)

```json
{
  "schema_version": "cagr-bootstrap-ci-v1",
  "portfolio": "concentrated",
  "point_estimate_cagr": 0.4443,
  "block_size": 20,
  "n_resamples": 1000,
  "random_seed": 20260615,
  "bootstrap_median": 0.4521,
  "bootstrap_p5": 0.2914,
  "bootstrap_p95": 0.5783,
  "ci_95_width_pp": 28.69,
  "credibility_score": "LOOSE",
  "verdict": "Wide 95% CI [29%, 58%] indicates point estimate is sample-dependent",
  "generated_at_utc": "..."
}
```

### 7.5 Cost stress (B5)

```json
{
  "schema_version": "cagr-cost-stress-v1",
  "portfolio": "concentrated",
  "per_cost_level": [
    { "cost_bps": 25,  "cagr": 0.4443, "max_dd": -0.2592, "sharpe": 1.40 },
    { "cost_bps": 50,  "cagr": 0.3872, "max_dd": -0.2638, "sharpe": 1.21 },
    { "cost_bps": 75,  "cagr": 0.3318, "max_dd": -0.2691, "sharpe": 1.03 },
    { "cost_bps": 100, "cagr": 0.2611, "max_dd": -0.2745, "sharpe": 0.83 },
    { "cost_bps": 150, "cagr": 0.1419, "max_dd": -0.2868, "sharpe": 0.46 }
  ],
  "sensitivity_pp_per_bp": -0.242,
  "cagr_at_25bps": 0.4443,
  "cagr_at_100bps": 0.2611,
  "robustness_score": "MODERATE",
  "verdict": "Survives 50bps comfortably, fragile above 100bps",
  "generated_at_utc": "..."
}
```

### 7.6 Regime decomposition (B6)

```json
{
  "schema_version": "cagr-regime-decomposition-v1",
  "portfolio": "concentrated",
  "per_regime": {
    "strong_bull": { "days": 88, "share": 0.05, "annualized_return_pct": 142.1, "sharpe": 3.41, "contribution_to_full_cagr_pp": 7.2 },
    "bull":        { "days": 530, "share": 0.30, "annualized_return_pct": 78.4,  "sharpe": 1.92, "contribution_to_full_cagr_pp": 23.4 },
    "neutral":     { "days": 706, "share": 0.40, "annualized_return_pct": 9.8,   "sharpe": 0.41, "contribution_to_full_cagr_pp": 3.9 },
    "bear":        { "days": 354, "share": 0.20, "annualized_return_pct": -42.6, "sharpe": -1.51, "contribution_to_full_cagr_pp": -8.5 },
    "deep_bear":   { "days": 90,  "share": 0.05, "annualized_return_pct": -68.3, "sharpe": -2.04, "contribution_to_full_cagr_pp": -3.4 }
  },
  "concentration": {
    "top_regime_share": 0.55,
    "score": "TILTED"
  },
  "bull_only_cagr_pct": 78.4,
  "neutral_only_cagr_pct": 9.8,
  "bear_only_cagr_pct": -42.6,
  "verdict": "Directional bull beta — defensive performance weak.",
  "generated_at_utc": "..."
}
```

### 7.7 Combined credibility (B7, optional)

`outputs/cagr_credibility/<portfolio>_report.md` — markdown 한 페이지.

```markdown
# Concentrated CAGR Credibility Report — 2026-06-19

| Test | Result | Verdict |
|---|---|---|
| Headline | 44.43% over 7.03y | reference only |
| Walk-forward OOS avg | 70.3% | inflation 1.75x vs single OOS |
| Factor α annualized | 3.21% (R²=0.81) | α-share 7.2% of CAGR — mostly β |
| Start-date robustness | range 40.9pp | FRAGILE — 2021 start = 22.8% |
| Bootstrap 95% CI | [29.1%, 57.8%] | LOOSE — wide range |
| Cost robustness | 100bps = 26.1% | MODERATE — fragile above 100bps |
| Regime concentration | top 55% | TILTED — bull-dependent |

**Overall verdict: LOW credibility.**
**Real engine alpha: ~3.2% annualized.** The 44.43% headline is dominated by
market β (1.18 SPY + 0.42 QQQ tilt + 0.31 semis), bull-regime concentration,
and a favorable 2019-06 start date. Reducing universe survivorship (Workstream C)
expected to compress headline ~10pp closer to honest engine CAGR.

Generated by tools/run_cagr_credibility_report.py at <timestamp>.
```

---

## 8. Smoke Test 의무 체크리스트 (각 PR)

### 8.1 모든 PR

- [ ] `tests/<tool_name>_smoke.py` 존재.
- [ ] `tools/run_pr_validation.py` 의 DEFAULT_TESTS list에 등록.
- [ ] Smoke 최소 5 test (B1-B6), 7-10 test (C1-C5).
- [ ] 실행 시간 각 smoke ≤ 10초 (`run_pr_validation` 전체 제약).
- [ ] `[LOCAL] python3 tests/<smoke>.py` 통과 시 stdout 마지막 줄 `N/N passed`.

### 8.2 Math 검증 smoke (workstream B 필수)

- [ ] **Synthetic data로 known answer 회복** (각 도구):
  - B1: 균등 +10%/yr equity 곡선 → 4 windows 모두 10% CAGR, inflation_indicator=1.0
  - B2: portfolio = 1.0 × SPY → α≈0, β_SPY≈1.0, R²≈1.0
  - B3: 동일 곡선 → 모든 start date에서 동일 CAGR → range_pp = 0
  - B4: 평탄 곡선 (return ≡ 10%/yr) → CI 좁음
  - B6: 모든 days = bull → 한 regime contribution = 100%

### 8.3 Edge case smoke (필수)

- [ ] Empty equity curve → "insufficient_data" status, no crash
- [ ] NaN 일자 → 정확히 drop
- [ ] Single date → graceful "single_day_no_cagr"
- [ ] Mismatched dates between curve and factor → align + count dropped
- [ ] Schema validation: output JSON이 §7 schema와 정확히 일치

### 8.4 Reproducibility smoke

- [ ] B4: 같은 seed 두 번 실행 → 정확히 같은 CI

---

## 9. Sidecar wiring

### 9.1 위치

`tools/run_full_rebuild_sidecars.py:~219` (performance_ledger 다음 줄).

순서:
```bash
  # ... performance_ledger ...
  python tools/run_performance_ledger.py ...

  # Workstream B sidecars — CAGR credibility measurement (added 2026-06-19).
  # All non-fatal (|| true). Cheap except cost_stress (skipped by default).
  python tools/run_cagr_walkforward.py --latest-run outputs --output-dir outputs/cagr_walkforward 2>&1 | tee outputs/full_rebuild_logs/cagr_walkforward.log || true
  python tools/run_factor_attribution.py --latest-run outputs --output-dir outputs/factor_attribution 2>&1 | tee outputs/full_rebuild_logs/factor_attribution.log || true
  python tools/run_cagr_start_date_sensitivity.py --latest-run outputs --output-dir outputs/cagr_start_date_sensitivity 2>&1 | tee outputs/full_rebuild_logs/cagr_start_date_sensitivity.log || true
  python tools/run_cagr_bootstrap_ci.py --latest-run outputs --output-dir outputs/cagr_bootstrap_ci 2>&1 | tee outputs/full_rebuild_logs/cagr_bootstrap_ci.log || true
  python tools/run_cagr_regime_decomposition.py --latest-run outputs --output-dir outputs/cagr_regime_decomposition 2>&1 | tee outputs/full_rebuild_logs/cagr_regime_decomposition.log || true
  # cost_stress is heavy (5 broker_replay reruns); off by default
  if [ "${ENABLE_COST_STRESS:-false}" = "true" ]; then
    python tools/run_cagr_cost_stress.py --latest-run outputs --output-dir outputs/cagr_cost_stress 2>&1 | tee outputs/full_rebuild_logs/cagr_cost_stress.log || true
  fi
  # Aggregate credibility report (reads all of the above)
  python tools/run_cagr_credibility_report.py --latest-run outputs --output-dir outputs/cagr_credibility 2>&1 | tee outputs/full_rebuild_logs/cagr_credibility.log || true
```

### 9.2 Workstream C universe sidecar는 안 들어감

C는 pre-pipeline 데이터 작업이라 sidecar에 안 들어감. C4가 `build_universe_monthly` 자체를 수정해서 활성화.

---

## 10. 필수 출력 형식

### 10.1 매 작업 시작 시 verification preamble

```
Verification preamble — <UTC timestamp>

Location confirmation:
  [LOCAL]  clone path: <path>
  [LOCAL]  last `git fetch origin`: <timestamp>
  [GITHUB] api access: ok

Branch SHAs:
  origin/master = <sha>
  origin/codex/<my-branch> = <sha or "not yet created">

Existing branches on 2026-06-19:
  <count>  # if > 5, STOP and report to user

Today's plan:
  Workstream <X>, PR <Y>: <name>
  Branch to create: codex/<x-y>-20260619
  Base: <master | codex/...>
  Estimated time: <N hours>
  Smoke target: tests/<smoke_name>_smoke.py with <N> tests
```

### 10.2 매 PR 완료 시 status block

```
PR <X> complete:
  Branch:   codex/<name>-20260619
  Base:     <base>
  Commits:  <count> (<first_sha>..<last_sha>)
  Files added: <list>
  Files modified: <list> (should be empty for workstream B)
  Smoke:    <N>/<N> passed
  PR URL:   <github url>
  Workstream <X>/<total> goal: <Y>/<Z> PRs opened
```

### 10.3 매 workstream 완료 시

```
Workstream <A|B|C> complete.
PRs opened:
  PR Wx.1: <url> — status (open / merged)
  PR Wx.2: <url> — ...
Total smoke tests added: <N>
Total LOC added: <N>
Awaiting human review on: <N> PRs
Next workstream: <Y>
```

---

## 11. Math 정확성 가드 (B에 필수)

### 11.1 CAGR 공식 통일

모든 도구에서 동일:
```python
def compute_cagr(start_equity: float, end_equity: float, years: float) -> float:
    if start_equity <= 0 or end_equity <= 0 or years <= 0:
        return float("nan")
    return (end_equity / start_equity) ** (1.0 / years) - 1.0
```

`r1000_helpers.py`에 `compute_cagr_safe()` 헬퍼 추가 권장. 모든 B 도구가 그걸 import.

### 11.2 일수 → 년 변환

```python
years = (end_date - start_date).days / 365.25  # 365.25 (윤년 고려)
```

`days / 365`나 `days / 252` 사용 금지 (혼란 방지). 단 Sharpe annualization은 `sqrt(252)` 사용 (거래일 기준).

### 11.3 Log-return vs simple-return

- CAGR 비교: simple return `(e_t / e_{t-1}) - 1`.
- Sharpe + 회귀: log return `log(e_t / e_{t-1})` (additive 합성).
- Bootstrap: log return (block 합산 가능).
- Factor regression: simple return (계량경제 표준).

각 도구의 어디서 어느 걸 쓰는지 docstring에 명시.

### 11.4 Numpy random seed

B4 (bootstrap): `np.random.default_rng(20260615)`. 다른 도구는 random 안 씀.

### 11.5 Floating point 비교

`abs(a - b) < 1e-9` 사용. `==` 금지.

---

## 12. Escalation Triggers (즉시 중단 + 사용자 보고)

- 같은 날짜 (20260619)에 5개 초과 브랜치 생성됨.
- 어느 PR diff 가 50 파일 초과 (양산 신호).
- C4 `build_universe_monthly` 수정 후 기존 monthly universe row count 가 90% 미만으로 감소.
- B5 cost_stress 실행 후 broker_replay 메트릭이 기존 25bps 결과와 일치하지 않음.
- Workstream C1 의 SEC API rate limit 도달 (10 req/sec 초과).
- C5 workflow 가 다른 cron 워크플로우와 충돌.
- 사용자가 "stop" 또는 "잠깐" 메시지.

---

## 13. End acknowledgment

작업 완료 (12 PR 다 open) 후:

```
I read CODEX_IMPLEMENTATION_PLAN_7Y_FULL_CAGR_PIT (this prompt),
CODEX_GOAL_SETTING_BRIEF.md, CODEX_PROMPT_48H_ACTION_PACK.md.

12 PRs opened on branch namespace codex/*-20260619:
  Workstream A (7y lock):
    A1: <url>  (7y lock + 8y proxy blocked)
  Workstream B (CAGR credibility):
    B1: <url>  (walk-forward OOS)
    B2: <url>  (factor attribution)
    B3: <url>  (start-date sensitivity)
    B4: <url>  (bootstrap CI)
    B5: <url>  (cost stress)
    B6: <url>  (regime decomposition)
    B7: <url>  (combined report — optional)
  Workstream C (PIT universe):
    C1: <url>  (historical R1000 membership ETL)
    C2: <url>  (PIT ADR/cycle scanner)
    C3: <url>  (13F/Form4 PIT candidates)
    C4: <url>  (universe builder PIT integration, env-gated)
    C5: <url>  (auto-schedule workflow)

Total smoke tests added: <N>
Total LOC added: <N>
Branch namespace check: codex/*-20260619 count = 12 (matches plan).
No safety/gate/require-X-safety proliferation branches created.

Awaiting:
  - ChatGPT Pro review on B2 (factor regression math) + C4 (universe builder change)
  - User merge decision on PR order
  - First full rebuild after merges to validate sidecar wiring
```

🟦 [END OF PROMPT — Codex starts here] 🟦

---

## 사용 방법 (메타-노트, Codex에 붙이지 마세요)

1. `🟦 [PASTE TO CODEX FROM HERE] 🟦` ~ `🟦 [END OF PROMPT — Codex starts here] 🟦` 사이 복사.
2. Codex의 첫 응답이 §10.1 verification preamble로 시작하는지 확인. 안 그러면 "Re-read §0+§10.1, comply."
3. 매 PR 완료 시 §10.2 status block 출력하는지 확인.
4. 브랜치 namespace `codex/*-20260619` 외 다른 브랜치 생성 시 즉시 escalate.
5. 12개 PR이 정확한 수 — 13번째 PR 시도 시 reject.
6. Workstream A → B → C 순서가 강제 X (병렬 가능), 단 C4가 C1/C2/C3 출력 의존하므로 C 내부는 순서 있음.

## 왜 이 plan이 지난 2일 패턴을 막는가

| 지난 패턴 | 이 plan의 방어 |
|---|---|
| 73 브랜치 양산 | §3 "12 PR이 정확한 수, 5개 초과 시 STOP" |
| 같은 changeset의 변형 양산 | 각 PR이 정확히 1개 파일 추가 + smoke (diff bounded) |
| Selection 엔진 미접근 | C4가 명시적으로 `build_universe_monthly` 수정 (engine touch) |
| Bull-floor 검증 win 미적용 | A1이 7y lock 만들면서 ChatGPT Pro 리뷰에 "bull-floor도 promote 됐는지" 명시적 점검 포함 |
| 8년 proxy 양산 | A1 자체가 8년 차단 |
| Smoke 없는 commit | §8 의무 체크리스트 |
| Schema 자유 변경 | §7 정확한 schema 박아둠 |
| Math 부정확 | §11 가드 + smoke synthetic data 검증 |

---

**End of Codex Implementation Plan — 2026-06-19 KST**

Author: Claude Code.
Update protocol: 12 PR 모두 머지 후 또는 Workstream C 결과로 universe 변화 측정 후 재작성.
