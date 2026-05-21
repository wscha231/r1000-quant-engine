# Plan C v3.5 — ChatGPT Post-Disclosure Alpha 통합 추가사항
**Date**: 2026-05-20
**Status**: Incremental refinement to v3 (PLAN_C_V2_STRENGTHENED + Part E in elegant-sniffing-dragon.md)
**Source**: ChatGPT Pro 2nd review of v3 plan

---

## 1. 통합 결정

ChatGPT의 8개 가치 있는 추가:

| # | 항목 | 통합 위치 |
|---|---|---|
| 1 | FOLLOW + FADE 양방향 테스트 | Phase D6 확장 |
| 2 | `issuer_float_pct_owned` | Phase D1 schema |
| 3 | `post_filing_price_confirmation_score` | Phase D4 score 컴포넌트 |
| 4 | 13D를 별도 stream | NEW Phase D7 |
| 5 | Form 4 transaction code 필터 | Phase D5 명시화 |
| 6 | Event-based 데이터셋 분리 | Phase D2 아키텍처 |
| 7 | Multi-bucket manager 학습 | Phase D3 확장 |
| 8 | Crowded trade 감지 | Phase D4 fade-leg |

---

## 2. Phase D6 확장 — FOLLOW vs FADE 양방향 학습

**기존 v3 가정**: 매니저가 매수한 종목 → 따라가기 (follow signal)

**ChatGPT 통찰**: 13F는 long-only 보고. 너무 많은 매니저가 같이 산 종목은 이미 가격 반영, contrarian이 더 나을 수도 있음.

### 양방향 학습 매트릭스

```python
# Phase D6 검증 가설 확장
hypotheses = {
    # FOLLOW direction (기존)
    "H1_follow_high_pda":
        "high-PDA 매니저 매수 → 30d/60d/90d forward outperform",
    "H2_follow_consensus":
        "5+ high-PDA 매니저 동시 매수 → +5%/60d",
    "H3_follow_smallcap":
        "smallcap + high-PDA + new_position → CLSK 패턴 (+10%/90d)",

    # FADE direction (NEW)
    "H4_fade_crowding":
        "15+ 매니저 동시 보유 → 평균 underperform (이미 가격 반영)",
    "H5_fade_late_chasers":
        "low-PDA 매니저가 high-PDA 매니저 1분기 뒤따라 매수 → underperform",
    "H6_fade_large_increase":
        "single fund massive position increase → 이미 알려진 신호 → 약함",
}
```

### 새 컬럼 (Phase D4 출력 확장)

| 컬럼 | 의미 |
|---|---|
| `pda_follow_score` | high-PDA 매수 따라가기 강도 [0, 1] |
| `pda_fade_score` | crowding 회피 페널티 [0, 1] |
| `pda_net_signal` | follow − fade × crowding_multiplier |
| `pda_crowding_count` | 동일 종목 보유 매니저 수 |
| `pda_crowding_concentration_hhi` | Herfindahl-Hirschman 지수 (집중도) |

### Decision rule

```python
if pda_crowding_count > 15 and avg_excess_60d < -0.02:
    # Crowded + historically underperforms → fade
    signal = -pda_fade_score * 0.5  # 음수 가산점
elif pda_crowding_count < 5 and high_pda_buyers >= 2:
    # Sparse + high-PDA → follow strongly
    signal = pda_follow_score * 1.0
else:
    # Mixed → small follow with confidence decay
    signal = pda_follow_score * 0.3
```

---

## 3. Phase D1 schema 확장 — `issuer_float_pct_owned`

**핵심 문제 (ChatGPT 정확 지적)**:
- 펀드 입장: $5M 포지션 = 펀드 자산의 0.1% (작아 보임)
- T1 Energy 입장: $5M = float의 2% (실제로 큰 영향)

→ `position_size_pct_in_fund` 단독으론 small-cap 신호 약함

### Phase D1 schema 추가

```python
# data_pit/sec/13f_position_events.parquet schema
columns = {
    # 기존 (v3에 이미 있음):
    "manager_cik": str,
    "ticker": str,
    "available_from": datetime,
    "position_type": str,  # new/increased/decreased/closed
    "shares_delta": int,
    "value_delta_usd": float,
    "manager_position_weight": float,  # within-fund weight

    # NEW (ChatGPT 통찰):
    "issuer_market_cap_usd": float,
    "issuer_float_shares": int,
    "issuer_float_value_usd": float,
    "issuer_float_pct_owned_post_event": float,  # 발표 후 매니저 지분 / 발행사 float
    "issuer_float_pct_added": float,             # delta / float (event 강도)
    "issuer_dollar_volume_20d_avg": float,
    "manager_stake_to_dollar_volume": float,     # event 크기 / 일평균 거래대금
    "market_cap_bucket": str,  # micro <300M / small 300M-2B / mid 2B-10B / large >10B
}
```

### Score 활용

```python
def compute_issuer_float_impact_score(event):
    pct = event["issuer_float_pct_added"]

    if pct < 0.001:    # < 0.1% of float → 미미
        return 0.0
    elif pct < 0.01:   # < 1% of float → 약한 신호
        return 0.3
    elif pct < 0.05:   # 1-5% of float → 의미 있는 지분
        return 0.7
    elif pct < 0.10:   # 5-10% of float → 강한 신호 (13D 임박)
        return 0.9
    else:              # > 10% → 13D filing 필요할 정도
        return 1.0
```

→ T1 Energy / CLSK 패턴 정확히 포착.

---

## 4. Phase D4 score 컴포넌트 추가 — `post_filing_price_confirmation_score`

**ChatGPT 핵심 통찰**: 13F 발표 후 가격이 실제 반응했는지 확인. 발표 후 가격이 안 움직였으면 시장이 무시했다는 것 → 신호 약함.

### 가격 확정 점수 계산

```python
def compute_post_filing_price_confirmation(
    ticker: str,
    available_from: datetime,
    days_after: int = 10,
) -> dict:
    """
    공시 후 N일 동안 가격/거래량이 어떻게 반응했는지 측정.
    """
    pre_window  = (available_from - 10d, available_from)
    post_window = (available_from, available_from + days_after)

    # 가격 반응
    price_change = price[post_window.end] / price[available_from] - 1
    # 거래량 반응
    avg_vol_post = mean(volume[post_window])
    avg_vol_pre  = mean(volume[pre_window])
    vol_ratio = avg_vol_post / avg_vol_pre

    # 매수 압력 점수
    if price_change > 0.05 and vol_ratio > 1.5:
        return {"score": 1.0, "interpretation": "strong_confirmation"}
    elif price_change > 0.02 and vol_ratio > 1.2:
        return {"score": 0.7, "interpretation": "mild_confirmation"}
    elif price_change > 0 and vol_ratio > 1.0:
        return {"score": 0.4, "interpretation": "weak_confirmation"}
    elif price_change < -0.02:
        return {"score": -0.5, "interpretation": "market_rejected"}
    else:
        return {"score": 0.0, "interpretation": "no_reaction"}
```

### 최종 PDA score 공식 (v3.5)

```python
post_disclosure_alpha_score_v3_5 = (
    0.22 * manager_post_disclosure_alpha_score   # historical manager quality
  + 0.18 * event_strength_score                  # new vs increased vs trimmed
  + 0.16 * issuer_float_impact_score             # NEW: float % owned (CLSK)
  + 0.14 * multi_manager_convergence_score       # high-PDA 합의
  + 0.10 * post_filing_price_confirmation_score  # NEW: 가격 반응 확인
  + 0.08 * smallcap_discovery_score              # micro/small cap 보너스
  + 0.07 * sector_theme_fit_score                # 테마 일치
  + 0.05 * crowded_trade_penalty                 # NEW: 15+ 매니저 시 감점
)
```

**합계 = 1.0**. 모든 컴포넌트 [0, 1] 정규화. `crowded_trade_penalty`는 음수 가능.

---

## 5. Phase D7 신설 — 13D Activist Stream (별도)

**ChatGPT 통찰**: 13D는 13F와 본질적으로 다름.
- 13F: 분기 보유 보고 (지연 45일)
- 13D: 5% 이상 지분 + 지배/전략 의도 (10일 이내 신고, 빠름)
- 13G: 5% 이상 보유 but passive intent

### Phase D7 — 13D Event Stream (3일 작업)

NEW 파일들:
- `tools/run_13d_activist_event_collector.py` — SEC EDGAR에서 13D filing 수집
- `tools/run_13d_post_event_alpha.py` — 13D 발표 후 forward return 측정

### Schema

```python
# data_pit/sec/13d_activist_events.parquet
columns = {
    "event_id": str,
    "filer_cik": str,  # 13D 신고자
    "filer_name": str,
    "issuer_cik": str,
    "issuer_ticker": str,
    "filing_date": datetime,
    "accepted_at": datetime,
    "ownership_pct": float,
    "shares_owned": int,
    "amendment_number": int,  # 13D는 amendment 시리즈
    "intent_category": str,   # control / influence / passive / undisclosed
    "filer_quality_score": float,  # 학습됨 (activist track record)
}
```

### 13D score

```python
post_13d_alpha_score = (
    0.30 * activist_intent_score        # control > influence > passive
  + 0.20 * ownership_percent_score      # 5% < 10% < 15% < 20%+
  + 0.20 * amendment_add_score          # 신규 vs 증액 amendment
  + 0.15 * filer_quality_score          # historical activist alpha
  + 0.10 * smallcap_control_premium     # smallcap에서 13D 영향 증폭
  + 0.05 * post_filing_price_confirmation
)
```

### Top 13D filers (활동가 매니저)

학습 대상 (historical alpha 측정):
- Carl Icahn (Icahn Enterprises)
- Bill Ackman (Pershing Square — 이미 managers.csv)
- Elliott Investment Management (이미 managers.csv)
- ValueAct Capital
- Starboard Value
- Engaged Capital
- Land & Buildings
- Trian Fund Management
- Third Point (Daniel Loeb)

**Cron**: `sec_13d_event_collector.yml` — 주 1회 (Mon 09:00 KST)

---

## 6. Phase D5 명시화 — Form 4 transaction code 필터

**ChatGPT 정확 지적**: Form 4의 transaction codes는 의미가 다름.

| Code | 의미 | conviction 신호? |
|---|---|---|
| **P** | Open-market purchase | ✅ 강함 |
| **S** | Open-market sale | 🟡 약한 risk flag |
| **M** | Option exercise | ❌ 보상성, 무의미 |
| **A** | Award/grant (RSU vesting) | ❌ 보상성, 무의미 |
| **F** | Tax withholding | ❌ 의무성, 무의미 |
| **D** | Sale to issuer | ❌ 특수 |
| **G** | Gift | ❌ 무의미 |
| **C** | Conversion (preferred → common) | ❌ 무의미 |

### Phase D5 필터 명시

```python
# tools/run_sec_form4_parser.py 수정 필요
FORM4_CONVICTION_CODES = {"P"}  # only open-market buys
FORM4_SOFT_RISK_CODES = {"S"}   # sales — weak risk flag
FORM4_NOISE_CODES = {"M", "A", "F", "D", "G", "C"}  # exclude entirely

def filter_form4_for_conviction(raw_form4_df):
    # 1. Drop noise codes entirely
    df = raw_form4_df[~raw_form4_df["transaction_code"].isin(FORM4_NOISE_CODES)]

    # 2. Separate buys vs sales
    buys = df[df["transaction_code"].isin(FORM4_CONVICTION_CODES)]
    sales = df[df["transaction_code"].isin(FORM4_SOFT_RISK_CODES)]

    # 3. Cluster buy detection (NEW)
    cluster_buys = detect_cluster_buys(
        buys,
        time_window_days=30,
        min_insider_count=2,
    )

    return buys, sales, cluster_buys
```

---

## 7. Phase D2 아키텍처 — Event-based dataset 분리

**ChatGPT 제안 (개선됨)**:

```
[현재 v3 설계]
manager_alpha() → 한꺼번에 manager × ticker × forward_returns 계산
                  → 단일 parquet
                  → 멀티-period context 손실 (drop_duplicates)

[v3.5 개선]
data_pit/sec/13f_position_events.parquet  ← raw event log
                                             (manager × ticker × time)

data_pit/sec/post_disclosure_alpha_labels.parquet  ← forward returns
                                                     (event_id × horizon)

data_pit/sec/manager_disclosure_alpha_scores.parquet  ← aggregated stats
                                                        (manager × bucket × as_of_date)
```

### 데이터 흐름

```
13F filings (raw)
    ↓ tools/run_13f_position_event_builder.py
13f_position_events.parquet (이벤트 로그)
    ↓ tools/run_post_disclosure_alpha_labeler.py
post_disclosure_alpha_labels.parquet (forward returns)
    ↓ tools/run_manager_disclosure_alpha_scoring.py
manager_disclosure_alpha_scores.parquet (매니저 통계, walk-forward)
    ↓ r1000_features.py:load_pda_overlay()
score_pda_overlay column in scored_latest.csv
    ↓ (kill switch boundary)
    ↓ if cfg.pda_apply_to_live_score:
score 추가
```

### 장점

1. 각 단계 캐시 가능
2. as_of_date 별로 매니저 점수 재학습 (walk-forward 깔끔)
3. event_id로 양쪽 dataset join 가능
4. 미래 누출 차단 (label은 read-only, score는 events만 사용)

---

## 8. Phase D3 확장 — Multi-Bucket Manager 학습

**ChatGPT 통찰**: 매니저는 "전체 alpha"가 아니라 "어떤 컨텍스트에서 강한지"로 평가해야.

### Bucket 분리

매니저별로 다음 bucket마다 별도 alpha 측정:

```python
manager_pda_buckets = {
    # Market cap bucket
    "micro_cap":     ticker.mcap < 300M,
    "small_cap":     300M ≤ ticker.mcap < 2B,
    "mid_cap":       2B ≤ ticker.mcap < 10B,
    "large_cap":     ticker.mcap ≥ 10B,

    # Position type bucket
    "new_position":  position_type == "new",
    "increased":     position_type == "increased",
    "trimmed":       position_type == "decreased",

    # Sector bucket
    "tech":          sector in ["Technology", "Communication Services"],
    "healthcare":    sector == "Healthcare",
    "energy":        sector == "Energy",
    "consumer":      sector in ["Consumer Discretionary", "Consumer Staples"],
    "industrial":    sector == "Industrials",
    "financial":     sector == "Financials",

    # Recency bucket
    "recent_1y":     event_date >= as_of - 365d,
    "recent_3y":     event_date >= as_of - 1095d,
    "all_time":      all events,
}
```

### Output schema

```python
# manager_disclosure_alpha_scores.parquet
columns = {
    "manager_cik": str,
    "manager_name": str,
    "as_of_date": datetime,
    "bucket_key": str,  # e.g. "small_cap__new_position__recent_1y"
    "observation_count": int,
    "avg_excess_30d": float,
    "avg_excess_60d": float,
    "avg_excess_90d": float,
    "avg_excess_180d": float,
    "hit_rate_excess_positive_60d": float,
    "composite_pda_score": float,  # 0-1
    "confidence": float,  # sqrt(obs / 50)
}
```

### Live application

```python
def compute_ticker_pda_score_v3_5(ticker, latest_holdings, manager_scores):
    score = 0.0
    confidence = 0.0
    bucket_key = construct_bucket_key(ticker)  # e.g. "small_cap__new_position__recent_1y"

    for holding in latest_holdings[latest_holdings.ticker == ticker]:
        # 매니저의 특정 bucket에서의 alpha 가져오기
        manager_bucket_score = manager_scores.lookup(
            holding.manager_cik,
            bucket_key,
        )

        if manager_bucket_score is None:
            # fallback to manager's all-time alpha
            manager_bucket_score = manager_scores.lookup(
                holding.manager_cik,
                "all_time",
            )

        score += manager_bucket_score.composite_pda_score * holding.position_strength
        confidence += manager_bucket_score.confidence

    return (
        min(score / 3.5, 1.0),       # normalize
        min(confidence / 3.0, 1.0),  # normalize
    )
```

### 예시 효과

매니저 X의 일반 alpha = 0.4 (중간)
하지만 매니저 X의 **`small_cap__new_position__recent_1y`** bucket alpha = 0.85 (강함)

→ 매니저 X가 small_cap을 new_position으로 산 종목은 강한 신호
→ 매니저 X가 large_cap을 trimmed한 정보는 무시

→ Lansdowne(small-cap specialist) 효과 정확히 포착

---

## 9. Phase D4 추가 — Crowded Trade Detection

**ChatGPT 통찰**: 15+ 매니저가 보유한 NVDA-class 종목은 이미 가격 반영, contrarian 가능.

### Crowding 측정

```python
def compute_crowding_metrics(ticker, all_13f_holdings, lookback_quarters=4):
    recent_holdings = all_13f_holdings[
        all_13f_holdings.ticker == ticker
        & all_13f_holdings.report_period >= now - lookback_quarters * 90d
    ]

    metrics = {
        # 보유 매니저 수
        "manager_count": recent_holdings.manager_cik.nunique(),

        # 합산 지분 / float
        "aggregate_pct_of_float":
            recent_holdings.shares.sum() / ticker.float_shares,

        # 집중도 (HHI)
        "concentration_hhi":
            sum((m.shares / total_shares) ** 2 for m in recent_holdings),

        # 신규 진입 vs 정체
        "new_position_ratio":
            recent_holdings.is_new_position.mean(),

        # 추세 (분기 대비)
        "manager_count_trend":
            (current_qtr_count - prev_qtr_count) / prev_qtr_count,
    }
    return metrics
```

### Decision rule

```python
def crowding_signal(metrics, historical_crowded_excess_returns):
    """
    Historical 데이터로 학습:
    - 15+ 매니저 + 신규진입율 낮음 → 평균 60d excess return = ?
    - 15+ 매니저 + 신규진입율 높음 → ?
    - 5-15 매니저 + 신규진입율 높음 → ?
    """
    n = metrics["manager_count"]
    new_ratio = metrics["new_position_ratio"]
    trend = metrics["manager_count_trend"]

    if n >= 15 and new_ratio < 0.1 and trend < 0:
        # 이미 모두 들어왔고 빠지는 중 → fade
        return {"direction": "fade", "strength": 0.7}
    elif n >= 15 and new_ratio > 0.3:
        # 많지만 신규도 계속 들어옴 → 모멘텀
        return {"direction": "follow", "strength": 0.5}
    elif 5 <= n < 15 and new_ratio > 0.5:
        # 적당히 많고 새로 진입 → 모멘텀
        return {"direction": "follow", "strength": 0.9}
    elif n < 5:
        # 거의 안 알려진 종목 → high-PDA 매니저 시그널만 강하면 follow
        return {"direction": "follow", "strength": 0.6}
    else:
        return {"direction": "neutral", "strength": 0.3}
```

---

## 10. v3.5 Implementation Roadmap (Updated)

### Track A — Safety (BLOCKING, 1-2일)
1. **Phase C0.1 KILL SWITCH** (변경 없음, v3 동일)

### Track B — Data + Events (4-5일)
2. Phase C1 SEC workflow 트리거 (변경 없음)
3. Phase C1.5 Readiness audit (변경 없음)
4. **Phase D1 v3.5**: Event-based dataset (`13f_position_events.parquet` 분리) — ChatGPT 통찰 #6
5. **Phase D7 NEW**: 13D activist event stream — ChatGPT 통찰 #4

### Track C — Learning (5-7일)
6. **Phase D2 v3.5**: post_disclosure_alpha_labels.parquet (label dataset 분리)
7. **Phase D3 v3.5**: Multi-bucket manager 학습 (smallcap × new_position × recent) — ChatGPT 통찰 #7
8. **Phase D4 v3.5**: Float impact + price confirmation + crowding 점수 — ChatGPT 통찰 #2, #3, #8
9. **Phase D5 v3.5**: Form 4 transaction code 필터 명시 — ChatGPT 통찰 #5
10. **Phase D6 v3.5**: FOLLOW + FADE 양방향 학습 — ChatGPT 통찰 #1

### Track D — Validation (3-4일)
11. Phase C3 v3.5: Evidence fusion v2 + PDA v3.5 shadow
12. Phase C4: Broker-ledger challenger (7-scenario + PDA scenarios)

### Track E — Productization (1주)
13. Phase C5 ETF PIT (변경 없음)
14. Phase C6 Smart Money Top30 (PDA v3.5 + 13D + cluster Form4 포함)
15. Phase C7 After-service

### Track F — Final (last)
16. Phase C8 Full Auto promotion (변경 없음)
17. Phase C9 Regime multiplier calibration (변경 없음)

---

## 11. v3 → v3.5 Δ 요약

| 변경 항목 | 영향 |
|---|---|
| FOLLOW + FADE 양방향 | 13F crowded trade 우회 가능 |
| issuer_float_pct_owned | CLSK/T1 패턴 정확도 ↑ |
| post_filing_price_confirmation | 신호 강도 증폭 (false positive 감소) |
| 13D activist 분리 stream | Carl Icahn 류 강한 이벤트 캡처 |
| Form 4 P-only 필터 | RSU/세금 노이즈 제거 |
| Event-based dataset | 학습 깔끔, 캐시 효율 |
| Multi-bucket manager | "어떤 컨텍스트 specialist인지" 식별 |
| Crowded detection | NVDA-class 자동 회피 |

**총 NEW 파일**: +1 (`run_13d_activist_event_collector.py`)
**총 수정 파일**: 5 (D1/D2/D3/D4/D5)
**예상 추가 작업**: +2일 (v3 16-18일 → v3.5 18-20일)

---

## 12. 핵심 차별점 (vs hedgefollow, vs ChatGPT plan, vs v2)

| 기능 | hedgefollow | ChatGPT plan | v3.5 |
|---|:-:|:-:|:-:|
| 13F manager tracking | ✅ | ✅ | ✅ 34 verified |
| Form 4 insider buys | ✅ | ✅ | ✅ P-code only |
| **13D activist stream** | ❌ | 🟡 mentioned | ✅ **별도 stream** |
| **FOLLOW + FADE 양방향** | ❌ | ✅ | ✅ |
| **issuer_float % owned** | ❌ | ✅ | ✅ |
| **Price confirmation** | ❌ | ✅ | ✅ |
| **Multi-bucket manager** | ❌ | ✅ | ✅ |
| **Crowding detection** | ❌ | ✅ | ✅ |
| Convergence (insider × institutional) | 🟡 | ✅ | ✅ |
| Regime multiplier | ❌ | ❌ | ✅ |
| Industry sector tilt | ❌ | ❌ | ✅ |
| ETF 3-layer (static + curated + dynamic) | ❌ | 🟡 PIT only | ✅ |
| After-service infra (anomaly/drift) | ❌ | 🟡 | ✅ |
| Auto-improvement loop | ❌ | ❌ | ✅ Phase C8 |
| Kill switch | ❌ | ✅ | ✅ |
| Official/research separation | ❌ | ✅ | ✅ |

**결론**: v3.5 = ChatGPT의 safety + post-disclosure 정교함 + 내 regime/industry/discovery infra + after-service. **세 가지 plan 중 가장 완전**.
