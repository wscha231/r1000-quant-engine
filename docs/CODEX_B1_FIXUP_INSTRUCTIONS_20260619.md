# Codex Fix-Up Instructions — PR #142 (B1 walk-forward credibility)

> **이 문서를 Codex에 그대로 붙여넣어 PR #142에 commit 1개 추가하라.**
> 새 PR 만들지 말 것. 기존 PR #142 `codex/cagr-walkforward-20260619` 브랜치에 commit append.
> 출처 brief: `docs/CODEX_GOAL_SETTING_BRIEF.md`, `docs/CODEX_PROMPT_48H_ACTION_PACK.md`.

---

## 🟦 [PASTE TO CODEX FROM HERE] 🟦

Codex, PR #142 (`codex/cagr-walkforward-20260619`)에 Claude 리뷰 3건이 있다. 모두 코드/스키마/스모크 변경이고, **새 PR 만들지 말고 같은 브랜치에 commit 1개 append**. CI green 후 사용자 merge.

위치 규율: 모든 명령에 `[LOCAL]` 또는 `[GITHUB]` 태그. 예외 없음.

---

## 0. 작업 전 확인

```bash
[LOCAL]  cd <repo>
[LOCAL]  git fetch origin
[LOCAL]  git checkout codex/cagr-walkforward-20260619
[LOCAL]  git pull --ff-only origin codex/cagr-walkforward-20260619
[LOCAL]  git rev-parse --short HEAD    # 기대: ae98f95e 또는 이후
[GITHUB] gh pr view 142 --json mergeable,state,headRefName
[LOCAL]  python3 -c "import pandas, math; print('deps ok')"
```

`HEAD`가 ae98f95e가 아니면 멈추고 사용자에게 보고.

---

## 1. 수정 범위 (정확)

| # | 무엇 | 파일 | 라인 (현재) | 영향 |
|---|---|---|---|---|
| F1 | `extract_single_oos_cagr` fallback 시 verdict 오염 차단 | `tools/run_cagr_walkforward.py` | 128–143, 236, 237 | **misleading 차단** (가장 중요) |
| F2 | window 범위 2020–2026으로 확장 + partial을 평균에서 제외 | `tools/run_cagr_walkforward.py` | 28 (`WINDOW_YEARS`), 230–237 | "7년 전체 신빙성" 목적 정합 |
| F3 | 도구 명칭 정직성: "rolling calendar-year CAGR, NOT walk-forward retrain" 명시 | `tools/run_cagr_walkforward.py` docstring + `report.md` 본문 | module docstring + 277 | 용어 혼동 제거 |
| F4 | schema_version v1 → v2 (필드 추가·의미 변경) | `tools/run_cagr_walkforward.py` `SCHEMA_VERSION` 상수 | 상수 정의부 | 향후 호환성 |
| F5 | 스모크 갱신 (window 7개, partial 제외, fallback 분리, single_OOS_unavailable verdict) | `tests/cagr_walkforward_smoke.py` | 전체 | 회귀 방지 |
| F6 | sidecar wire (full rebuild 시 자동 실행되게 1줄 추가) | `tools/run_full_rebuild_sidecars.py` | performance_ledger 호출 다음 줄 | **머지 후 sidecar로 실행되게** (현재 wire 0) |

**금지**:
- 새 파일 추가 0 (smoke 동일 경로 갱신만).
- selection/scoring/target/cash 코드 0 수정.
- `r1000_helpers.py` 0 수정 (`compute_cagr_safe`는 그대로 OK).
- `tools/run_pr_validation.py` 0 수정 (이미 등록됨).
- F6 wire 외에 `run_full_rebuild_sidecars.py`의 다른 줄 0 수정 (cost_stress 등 다른 도구 활성화 금지).

---

## 2. F1 — fallback 시 verdict 분리 (가장 중요)

### 2.1 문제

현재 `summarize_portfolio()` (line ≈230–237):

```python
single_oos = extract_single_oos_cagr(metrics, fallback=valid_cagrs[-1] if valid_cagrs else None)
verdict, inflation = classify_verdict(single_oos, walk_avg)
```

`metrics.json`에 OOS CAGR 키가 없으면 `valid_cagrs[-1]` (= 마지막 rolling window CAGR)을 fallback한다. 그러면 `inflation = valid_cagrs[-1] / mean(valid_cagrs)` 가 되어 "마지막 window가 평균보다 큰가"를 잴 뿐 OOS lottery 측정과 의미가 다르다.

### 2.2 수정

**`extract_single_oos_cagr`을 fallback 없이 호출하고, fallback 진입을 별도 flag로 추적.**

#### 2.2.1 `extract_single_oos_cagr` 시그니처 변경

Before (line 128):
```python
def extract_single_oos_cagr(metrics: dict[str, Any], fallback: float | None) -> float | None:
    ...
    return fallback
```

After:
```python
def extract_single_oos_cagr(metrics: dict[str, Any]) -> float | None:
    """Return the metrics-reported single-window OOS CAGR, or None if absent.

    No fallback to rolling-window CAGRs: a missing metrics value yields a
    `single_oos_unavailable` verdict downstream, not a contaminated ratio.
    """
    direct_candidates = (
        metrics.get("single_oos_cagr"),
        metrics.get("oos_cagr"),
        metrics.get("oos_broker_cagr"),
        nested_get(metrics, ("windows", "oos", "cagr")),
        nested_get(metrics, ("windows", "OOS", "cagr")),
        nested_get(metrics, ("window_metrics", "oos", "cagr")),
        nested_get(metrics, ("is_oos", "oos_cagr")),
    )
    for value in direct_candidates:
        parsed = safe_float(value)
        if parsed is not None:
            return parsed
    return None
```

#### 2.2.2 `classify_verdict`에 unavailable 분기 추가

Before (line ≈200):
```python
def classify_verdict(single_oos_cagr: float | None, walk_forward_avg: float | None) -> tuple[str, float | None]:
    if single_oos_cagr is None or walk_forward_avg is None or walk_forward_avg <= 0.0:
        return VERDICT_INSUFFICIENT, None
    ratio = single_oos_cagr / walk_forward_avg
    ...
```

After:
```python
VERDICT_SINGLE_OOS_UNAVAILABLE = "single_oos_unavailable"  # 모듈 상수 영역에 추가

def classify_verdict(
    single_oos_cagr: float | None,
    walk_forward_avg: float | None,
) -> tuple[str, float | None]:
    if walk_forward_avg is None or walk_forward_avg <= 0.0:
        return VERDICT_INSUFFICIENT, None
    if single_oos_cagr is None:
        # metrics.json 에 single-window OOS CAGR 키가 없음 → ratio 계산 불가.
        # rolling 평균만으로 잘못된 verdict를 내지 않도록 별도 verdict로 표기.
        return VERDICT_SINGLE_OOS_UNAVAILABLE, None
    ratio = single_oos_cagr / walk_forward_avg
    if ratio <= 1.25:
        return VERDICT_CONSISTENT, ratio
    if ratio <= 2.0:
        return VERDICT_MODERATE, ratio
    return VERDICT_INFLATED, ratio
```

#### 2.2.3 호출부 갱신 (`summarize_portfolio`, line ≈236)

Before:
```python
single_oos = extract_single_oos_cagr(metrics, fallback=valid_cagrs[-1] if valid_cagrs else None)
verdict, inflation = classify_verdict(single_oos, walk_avg)
```

After:
```python
single_oos = extract_single_oos_cagr(metrics)
verdict, inflation = classify_verdict(single_oos, walk_avg)
single_oos_source = "metrics" if single_oos is not None else "unavailable"
```

그리고 반환 dict에 다음 필드 **추가** (line ≈245 근처, `single_oos_cagr` 옆):
```python
"single_oos_cagr_source": single_oos_source,  # "metrics" | "unavailable"
```

### 2.3 검증

`single_oos`가 None 일 때 verdict가 `single_oos_unavailable` 이고 inflation 이 `None` 이어야 함. 아래 F5 smoke 가 강제.

---

## 3. F2 — window 범위 + partial 평균 제외

### 3.1 문제

현재 `WINDOW_YEARS = (2023, 2024, 2025, 2026)` (line 28). 2019–2022가 빠져 **bear (2022) 가 평가에 안 들어감** → 방어력 측정 불가. 또한 2026 partial이 평균에 동등 비중으로 들어가 annualized 변동성으로 평균을 왜곡.

### 3.2 수정

#### 3.2.1 `WINDOW_YEARS` 확장 + partial 식별 분리

Before (line 28):
```python
WINDOW_YEARS = (2023, 2024, 2025, 2026)
```

After:
```python
# 7-year credibility audit: full calendar years 2020–2025 are completed,
# 2026 is partial (audit run time). The pre-2020 ≈7 months of the broker_replay
# equity curve (≈2019-06 → 2019-12) are intentionally NOT segmented as a
# window: a half-year window adds annualization noise without information
# beyond what 2020 already captures. 2022 (bear) is included so defensive
# regime credibility is visible.
FULL_WINDOW_YEARS = (2020, 2021, 2022, 2023, 2024, 2025)
PARTIAL_WINDOW_YEARS = (2026,)
WINDOW_YEARS = (*FULL_WINDOW_YEARS, *PARTIAL_WINDOW_YEARS)
# 결과: (2020, 2021, 2022, 2023, 2024, 2025, 2026)
```

#### 3.2.2 `yearly_window`의 partial 판정 수정

Before (line 165):
```python
"partial": bool(year == 2026),
```

After:
```python
"partial": bool(year in PARTIAL_WINDOW_YEARS),
```

#### 3.2.3 `summarize_portfolio` 의 average 계산: **partial 제외**

Before (line ≈230–234):
```python
windows = [yearly_window(curve, year) for year in WINDOW_YEARS]
valid_cagrs = [safe_float(row.get("cagr")) for row in windows]
valid_cagrs = [value for value in valid_cagrs if value is not None]

walk_avg = arithmetic_mean(valid_cagrs)
walk_geo = geometric_mean(valid_cagrs)
```

After:
```python
windows = [yearly_window(curve, year) for year in WINDOW_YEARS]

# 표시는 8개 윈도우 전부, 평균은 full calendar year만 (partial 제외).
full_year_cagrs = [
    safe_float(row.get("cagr"))
    for row in windows
    if not row.get("partial") and row.get("status") == "completed"
]
full_year_cagrs = [value for value in full_year_cagrs if value is not None]

partial_year_cagrs = [
    safe_float(row.get("cagr"))
    for row in windows
    if row.get("partial") and row.get("status") == "completed"
]
partial_year_cagrs = [value for value in partial_year_cagrs if value is not None]

walk_avg = arithmetic_mean(full_year_cagrs)
walk_geo = geometric_mean(full_year_cagrs)
```

#### 3.2.4 반환 dict 필드 갱신

Before (line ≈248–256):
```python
"walk_forward_cagr_avg": walk_avg,
"walk_forward_cagr_geomean": walk_geo,
"inflation_indicator": inflation,
"window_count": len(windows),
"completed_window_count": len(valid_cagrs),
"windows": windows,
```

After:
```python
"walk_forward_cagr_avg": walk_avg,             # full-year only
"walk_forward_cagr_geomean": walk_geo,         # full-year only
"inflation_indicator": inflation,
"window_count": len(windows),                  # 표시된 윈도우 수 (8)
"completed_full_year_count": len(full_year_cagrs),
"completed_partial_year_count": len(partial_year_cagrs),
"partial_year_cagrs_for_reference_only": partial_year_cagrs,
"windows": windows,
```

(주의: `completed_window_count` 키는 **삭제**. 의미가 모호해짐 → 명확한 두 키로 대체.)

### 3.3 검증

- `walk_forward_cagr_avg`는 항상 full year 만의 평균이어야 함.
- partial year CAGR은 `windows[].cagr`로 표시되지만 `walk_forward_cagr_avg` 분모에서 빠짐.
- F5 smoke 가 이걸 강제.

---

## 4. F3 — 명칭 정직성 (docstring + report)

### 4.1 모듈 docstring 갱신 (파일 상단)

Before (≈line 1–20, 정확한 줄은 너의 파일에서 확인):
```python
"""... (현재 docstring) ..."""
```

After (전체 교체):
```python
"""CAGR walk-forward credibility audit (measurement only).

Inputs:
  outputs/broker_replay/<portfolio>/equity_curve.csv
  outputs/broker_replay/<portfolio>/metrics.json

What this measures:
  Rolling calendar-year CAGR over the same already-trained broker_replay
  equity curve. The curve is segmented into 7 calendar windows
  (2020–2025 full, 2026 partial). Average and geometric mean are
  computed over FULL years only; the 2026 partial is reported for
  reference but never enters the average. The pre-2020 ≈7 months of
  the curve are not segmented (would add annualization noise without
  new information beyond 2020).

What this is NOT:
  This is NOT walk-forward retrain CAGR. The model is not re-trained per
  window; only the existing equity curve is re-segmented. True walk-forward
  retrain CAGR (4 separate train_walkforward calls, one per OOS year)
  requires re-running r1000_pipeline and is out of scope for this sidecar.

Outputs:
  outputs/cagr_walkforward/<portfolio>_summary.json  (schema-versioned)
  outputs/cagr_walkforward/report.md                  (table view)

This sidecar does not modify selection, scoring, target books, cash policy,
sizing, promotion state, or live trading. It only reads broker_replay
artifacts and writes a measurement summary.
"""
```

### 4.2 `write_report`의 본문 갱신 (`tools/run_cagr_walkforward.py`, line ≈277)

Before:
```python
"Measurement-only audit of broker-ledger CAGR stability across 2023, 2024, 2025, and 2026 partial windows.",
```

After:
```python
"Rolling calendar-year CAGR stability over the same trained broker-ledger equity curve.",
"Windows: 2020–2025 (full), 2026 (partial). Average uses full years only; the 2026 partial is shown for reference.",
"This is NOT walk-forward retrain CAGR — no model is re-trained per window.",
```

(3줄로 분리. 기존 한 줄 삭제 후 위 3줄 삽입.)

---

## 5. F4 — schema_version bump

### 5.1 상수 변경

Before (어딘가에서):
```python
SCHEMA_VERSION = "cagr-walkforward-v1"
```

After:
```python
SCHEMA_VERSION = "cagr-walkforward-v2"
```

### 5.2 v2 변경 사유 (commit message 인용용)

- 추가 필드: `single_oos_cagr_source`, `completed_full_year_count`, `completed_partial_year_count`, `partial_year_cagrs_for_reference_only`
- 삭제 필드: `completed_window_count`
- 의미 변경: `walk_forward_cagr_avg` 분모가 partial 제외 (조용한 의미 변경 방지 위해 bump)
- 신규 verdict: `single_oos_unavailable`

---

## 6. F5 — smoke 갱신 (회귀 방지)

`tests/cagr_walkforward_smoke.py` 갱신. 기존 6개 테스트를 다음과 같이 수정·확장.

### 6.1 합성 곡선 길이 확장

기존 smoke 는 `2023-01-01 ~ 2026-06-30`. 갱신: `2020-01-01 ~ 2026-06-30` (window 정의와 일치 — pre-2020 데이터는 segmented window에 안 들어가므로 합성 데이터도 거기서 시작).

도우미 함수 추가 (모듈 상단):
```python
def _build_compound_curve(start: date, end: date, annual_rate: float, init_eq: float = 100_000.0) -> pd.DataFrame:
    days = pd.date_range(start, end, freq="B")  # 영업일만
    if len(days) == 0:
        return pd.DataFrame(columns=["date", "equity"])
    daily_rate = (1.0 + annual_rate) ** (1.0 / 252.0) - 1.0
    eq = init_eq * (1.0 + daily_rate) ** (np.arange(len(days)))
    return pd.DataFrame({"date": days, "equity": eq})
```

### 6.2 test_known_answer_and_no_mutation 갱신

before/after (요지):
- +10%/yr curve 생성 (2020-01-01 ~ 2026-06-30).
- `metrics.json`에 `windows.oos.cagr=0.10` 명시.
- 기대값:
  - `window_count == 7` (2020, 2021, …, 2026)
  - `completed_full_year_count == 6` (2020–2025)
  - `completed_partial_year_count == 1` (2026)
  - `walk_forward_cagr_avg ≈ 0.10` (±1e-6)
  - 각 full year `windows[year]["cagr"]` ≈ 0.10
  - 2026 partial 의 `cagr`도 ≈ 0.10 이지만 average에 들어가지 않음 → 별도 assertion: 평균 계산 시 partial 제외 확인
    ```python
    expected_avg = sum(0.10 for _ in range(6)) / 6
    assert math.isclose(summary["walk_forward_cagr_avg"], 0.10, rel_tol=0, abs_tol=1e-6)
    assert math.isclose(expected_avg, 0.10, rel_tol=0, abs_tol=1e-9)
    ```
  - `single_oos_cagr == 0.10`
  - `single_oos_cagr_source == "metrics"`
  - `inflation_indicator ≈ 1.0`
  - `verdict == "single_oos_consistent_with_rolling_avg"`
- equity_curve.csv 와 metrics.json 의 mtime + bytes 가 변경되지 않음 (no-mutation).

### 6.3 새 test: test_fallback_unavailable_yields_unavailable_verdict

```python
def test_fallback_unavailable_yields_unavailable_verdict() -> None:
    """metrics.json 에 OOS CAGR 키가 전혀 없으면 verdict=single_oos_unavailable
    이고 inflation_indicator=None. 절대 rolling fallback으로 ratio 계산하지 말 것."""
    with _tempdir() as root:
        curve = _build_compound_curve(date(2020, 1, 1), date(2026, 6, 30), 0.10)
        _write_curve(root / "broker_replay" / "main", curve)
        # metrics 에 cagr 만 있고 oos/windows.oos 키 0
        _write_json(root / "broker_replay" / "main" / "metrics.json", {
            "metric_mode": "broker_ledger_next_close",
            "cagr": 0.10,
        })
        # concentrated 같은 식으로 작성 (또는 main 만 들어가도 무방하게 도구 처리)
        summary = run_walkforward(root)["summaries"]["main"]
        assert summary["single_oos_cagr"] is None
        assert summary["single_oos_cagr_source"] == "unavailable"
        assert summary["walk_forward_cagr_avg"] is not None
        assert math.isclose(summary["walk_forward_cagr_avg"], 0.10, rel_tol=0, abs_tol=1e-6)
        assert summary["inflation_indicator"] is None
        assert summary["verdict"] == "single_oos_unavailable"
```

### 6.4 새 test: test_partial_windows_excluded_from_average

```python
def test_partial_windows_excluded_from_average() -> None:
    """2026 partial CAGR이 극단적으로 다르더라도 walk_forward_cagr_avg 는
    2020-2025 full year 만의 평균이어야 한다."""
    with _tempdir() as root:
        # 2020-01 ~ 2025-12: +10%/yr  (full year cagr ≈ 0.10)
        seg1 = _build_compound_curve(date(2020, 1, 1), date(2025, 12, 31), 0.10)
        # 2026-01 ~ 2026-06: +100%/yr equivalent (partial은 평균에 들어가면 안 됨)
        seg2 = _build_compound_curve(date(2026, 1, 2), date(2026, 6, 30), 1.0,
                                     init_eq=float(seg1["equity"].iloc[-1]))
        curve = pd.concat([seg1, seg2], ignore_index=True)
        _write_curve(root / "broker_replay" / "main", curve)
        _write_json(root / "broker_replay" / "main" / "metrics.json", {
            "metric_mode": "broker_ledger_next_close",
            "cagr": 0.15,
            "windows": {"oos": {"cagr": 0.10}},
        })
        s = run_walkforward(root)["summaries"]["main"]
        # walk_forward_cagr_avg 은 2020-2025 평균 ≈ 0.10
        assert math.isclose(s["walk_forward_cagr_avg"], 0.10, rel_tol=0, abs_tol=5e-3)
        # 2026 partial은 windows에는 정확히 1개 있고 평균에는 안 들어감
        partial_rows = [w for w in s["windows"] if w["partial"]]
        assert len(partial_rows) == 1
        assert partial_rows[0]["year"] == 2026
        assert partial_rows[0]["cagr"] is not None and abs(partial_rows[0]["cagr"]) > 0.5
        # 평균이 partial에 흔들리지 않았음 → inflation 도 partial 영향 없음
        assert s["verdict"] == "single_oos_consistent_with_rolling_avg"
```

### 6.5 기존 test 보강

- `test_empty_curve_is_insufficient`: 빈 곡선 → `completed_full_year_count == 0`, `completed_partial_year_count == 0`, `verdict == "insufficient_data"`.
- 기존 `test_inflation_indicator_matches_ratio` 가 있으면 fallback 케이스 제거, metrics-only 케이스만 남김.

### 6.6 smoke 실행 명령

```bash
[LOCAL] python3 tests/cagr_walkforward_smoke.py
[LOCAL] python3 tools/run_pr_validation.py --only cagr_walkforward
[LOCAL] python3 tools/run_pr_validation.py     # 전체, < 30s 통과해야
```

---

## 6.7 F6 — sidecar wire (full rebuild 자동 실행)

### 6.7.1 문제

검증: `tools/run_full_rebuild_sidecars.py`에서 `cagr_walkforward` 호출 0건. 머지해도 다음 full rebuild에서 sidecar로 안 돌아감 — 도구는 있지만 호출자가 없음.

### 6.7.2 수정

`tools/run_full_rebuild_sidecars.py`에서 `run_performance_ledger.py` 호출 다음 줄에 1줄 추가.

찾기: 다음 패턴이 있는 줄을 grep으로 찾는다 (정확한 줄 번호는 사용자 환경에 따라 다를 수 있음).
```bash
[LOCAL] grep -n "run_performance_ledger.py" tools/run_full_rebuild_sidecars.py
```

찾은 줄 **바로 다음**에 다음 한 줄을 삽입:
```bash
  python tools/run_cagr_walkforward.py --latest-run outputs --output-dir outputs/cagr_walkforward 2>&1 | tee outputs/full_rebuild_logs/cagr_walkforward.log || true
```

규칙:
- `|| true` 로 non-fatal (실패해도 다음 sidecar 진행).
- `tee` 로 로그 보존.
- 들여쓰기는 주변 sidecar 호출과 동일 (2 space).
- **다른 줄 일절 수정 금지** (cost_stress 등 활성화 시도 금지).

### 6.7.3 검증

```bash
[LOCAL] grep -c "run_cagr_walkforward.py" tools/run_full_rebuild_sidecars.py    # 기대: 1
[LOCAL] python3 -c "import ast; ast.parse(open('tools/run_full_rebuild_sidecars.py').read())"  # syntax OK
```

shell script가 아니라 Python wrapper면 syntax check 무의미. 그래도 diff는 1줄 추가만 있어야 함.

```bash
[LOCAL] git diff tools/run_full_rebuild_sidecars.py
# 기대: + 1줄, - 0줄
```

---

## 7. Commit + Push 절차

```bash
[LOCAL] git status -s          # 변경된 3 파일만 확인 (run_cagr_walkforward.py, smoke, run_full_rebuild_sidecars.py)
[LOCAL] git diff --stat
[LOCAL] git add tools/run_cagr_walkforward.py tests/cagr_walkforward_smoke.py tools/run_full_rebuild_sidecars.py
[LOCAL] git commit -m "$(cat <<'EOF'
fix(B1): isolate fallback verdict + simplify windows 2020-2026 + wire sidecar

Addresses Claude review findings on PR #142:

F1 (fallback verdict contamination — silent misleading risk):
  extract_single_oos_cagr no longer accepts a fallback. When metrics.json
  lacks a single-window OOS CAGR key, classify_verdict returns the new
  "single_oos_unavailable" verdict with inflation_indicator=None. The
  previous fallback to valid_cagrs[-1] turned inflation into "is the last
  rolling window above the average?" which is unrelated to OOS lottery
  detection. New field single_oos_cagr_source in {"metrics","unavailable"}
  for downstream consumers to disambiguate.

F2 (window range + partial-year average distortion):
  WINDOW_YEARS extended to (2020, 2021, 2022, 2023, 2024, 2025, 2026).
  Only 2026 is flagged partial; pre-2020 ≈7 months of the equity curve are
  intentionally not segmented (would add annualization noise). walk_forward_
  cagr_avg and _geomean use FULL_WINDOW_YEARS (2020-2025) only; the 2026
  partial is displayed in windows[] but never enters the average. 2022 bear
  is now included in the credibility audit, restoring defensive-regime
  visibility (the previous 2023-2026 window was all bull/AI-rally).
  Schema fields changed: completed_window_count removed; replaced with
  completed_full_year_count + completed_partial_year_count +
  partial_year_cagrs_for_reference_only.

F3 (terminology honesty):
  Module docstring + report.md body explicitly state this is "rolling
  calendar-year CAGR over the same trained broker_replay equity curve" and
  "NOT walk-forward retrain CAGR" (which would require re-running
  r1000_pipeline with separate train_walkforward calls per OOS year).

F4 (schema bump v1 -> v2):
  Field additions + meaning change of walk_forward_cagr_avg (now full-year
  only) + new verdict enum value justify a version bump for downstream
  consumers (W5 public report).

F5 (smoke regression coverage):
  - synthetic curve (2020-01-01 -> 2026-06-30), 7 windows, 6 full
  - known-answer test asserts walk_forward_cagr_avg == 0.10 with 6 full
    years at +10%/yr (2026 partial present but excluded from mean)
  - new test_fallback_unavailable_yields_unavailable_verdict: missing
    metrics OOS key -> verdict "single_oos_unavailable", inflation None,
    no contamination of walk_forward_cagr_avg by fallback
  - new test_partial_windows_excluded_from_average: 2026 partial at
    annualized +100% does not move the mean of 2020-2025 at +10%
  - existing tests adjusted to new schema (completed_full_year_count etc.)

F6 (sidecar wire — make B1 actually run on rebuilds):
  Add 1 line to tools/run_full_rebuild_sidecars.py after the existing
  run_performance_ledger.py call so the next full rebuild generates the
  cagr_walkforward summary automatically. Non-fatal (|| true) so a B1
  failure does not break the rebuild. No other sidecar line changed.

Measurement-only: 0 changes to selection, scoring, target books, cash policy,
sizing, promotion state, or live trading. r1000_helpers.compute_cagr_safe
unchanged. tools/run_pr_validation.py unchanged (already registered).

https://claude.ai/code/session_01EFuqqTBYNezRzskPLMHdKU
EOF
)"
[LOCAL] git push origin codex/cagr-walkforward-20260619
[GITHUB] gh pr view 142 --json mergeable,statusCheckRollup
```

---

## 8. PR 본문 갱신 (선택, 권장)

PR #142 description 끝에 다음 단락 추가 (사람이 한 줄 추가):

```
---
Update 2026-06-19 (post-Claude review):
- F1 fallback verdict isolated (single_oos_unavailable)
- F2 windows simplified to 2020-2026 (2020-2025 full + 2026 partial),
  2026 partial excluded from walk_forward_cagr_avg; 2022 bear now in scope
- F3 docstring + report.md clarified as rolling, not walk-forward retrain
- F4 schema bumped v1 -> v2
- F5 smoke replaced with 2020-01 to 2026-06 synthetic + 2 new tests
  (fallback unavailable, partial excluded from average)
- F6 sidecar wired into tools/run_full_rebuild_sidecars.py (1 line, non-fatal)
  so the next full rebuild generates outputs/cagr_walkforward/ automatically
Detail: see commit message of the last commit and
docs/CODEX_B1_FIXUP_INSTRUCTIONS_20260619.md (if committed).
```

---

## 9. 작업 후 출력 (사용자 보고)

작업 종료 시 다음을 정확히 출력:

```
PR #142 fix-up complete:
  Branch:  codex/cagr-walkforward-20260619
  Commits added: 1
  Files changed: 3  (tools/run_cagr_walkforward.py, tests/cagr_walkforward_smoke.py,
                     tools/run_full_rebuild_sidecars.py [+1 line wiring])
  Files NOT touched (confirmed): r1000_helpers.py, tools/run_pr_validation.py,
    any selection/scoring/target/cash/sizing/live-trading code, any new file.
  Sidecar wire check:
    grep -c "run_cagr_walkforward.py" tools/run_full_rebuild_sidecars.py  →  1
    git diff tools/run_full_rebuild_sidecars.py                            →  +1 line, -0
  Smoke results:
    cagr_walkforward smoke:  <N>/<N> passed (was 6, expected ≥ 8)
    run_pr_validation full:  <N>/<N> passed, < 30s
  Schema:  v1 -> v2 (single_oos_cagr_source, completed_full_year_count,
           completed_partial_year_count, partial_year_cagrs_for_reference_only)
  Verdict enum gained: single_oos_unavailable
  PR view:  https://github.com/wscha231/r1000-quant-engine/pull/142
  CI status: <green/pending/red>

Awaiting:
  - Claude / ChatGPT Pro re-review of F1-F6 fix
  - User merge decision on PR #142
  - Next: B2 alpha/beta attribution per docs/CODEX_WALKFORWARD_PUBLIC_REPORT_PLAN.md §5.2
```

---

## 10. 금지 사항 (작업 종료 검증)

다음 중 하나라도 발생하면 즉시 사용자 보고:

- 새 브랜치 생성 (이 작업은 PR #142 브랜치에 commit 1개만 추가).
- 새 PR 생성.
- `r1000_helpers.py` 수정.
- `r1000_pipeline.py`, `r1000_features.py`, `r1000_signals.py`, `r1000_candidate_lanes.py`, `tools/run_broker_ledger_replay.py`, `tools/run_alphaops_vnext_policy_replay.py` 중 하나 이상 수정.
- `tools/run_full_rebuild_sidecars.py`의 F6 wire **외** 다른 줄 수정 (cost_stress 등 다른 도구 활성화 시도 즉시 reject).
- 새 파일 추가 (smoke 갱신만 허용).
- production target / cash policy / live trading 영향.
- workflow_dispatch 실행.
- master 직접 push.

🟦 [END OF PROMPT — Codex starts here] 🟦

---

## 사용 방법 (메타-노트, Codex에 붙이지 마세요)

1. `🟦 [PASTE TO CODEX FROM HERE] 🟦` ~ `🟦 [END OF PROMPT — Codex starts here] 🟦` 사이를 복사.
2. Codex에 붙여넣기.
3. Codex 첫 응답이 §0 verification 명령들로 시작하는지 확인. HEAD SHA가 `ae98f95e`인지 명시했는지 검증.
4. 매 단계 commit 전에 §10 금지 사항 위반 없는지 사용자가 한 번 더 확인.
5. push 후 CI green 확인 → 사용자가 머지.

## 사용자 추천 대비 차이

| 사용자가 추천 시 보고 싶었던 것 | 본 지시에서 반영 |
|---|---|
| schema 충돌 없음 확인 | F4 schema bump v1→v2 — 미래 충돌 방지 |
| 용어 혼동 없음 | F3 docstring + report 본문 명시 |
| fallback misleading risk 없음 | F1 verdict 분리 + single_oos_unavailable 신규 |
| 추가로: 2022 bear 빠짐 | F2 window 2020-2025 확장 — 사용자 추천보다 한 단계 더 |

이 fix 후 PR #142는 안심하고 머지 가능. 다음은 **B2 alpha/beta attribution** (Phase 1, MASTER_PRIORITY §1 STAGE 1).

---

**End of Codex B1 Fix-up Instructions — 2026-06-19 KST.**
