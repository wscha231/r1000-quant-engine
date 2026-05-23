# Codex Handoff — Plan C v3.5 Implementation Specification

**문서 작성일**: 2026-05-20
**대상 에이전트**: Codex (background coding agent)
**기준 plan**: `/root/.claude/plans/elegant-sniffing-dragon.md` Part F (v3.5 FINAL)
**보조 참조**: `PLAN_C_V3_5_CHATGPT_INTEGRATED_20260520.md` (on branch `claude/short-rs-plus-sec-evidence-merged`)

---

## 1. Mission Statement

Codex 에이전트가 **Plan C v3.5 — Post-Disclosure Alpha (PDA) framework**를 13~22일 일정으로
**병렬 멀티 브랜치 전략**으로 구현한다. 본 문서는:

1. 각 phase별 정확한 변경 위치 (`file:line`)
2. 브랜치 / PR 경계 / 머지 순서
3. 각 PR의 verification gate
4. Kill switch + auto-promote 차단 safety net
5. 의존성 그래프

---

## 2. Non-Goals (절대 하지 말 것)

- ❌ `sec_evidence_apply_to_live_score` 또는 `pda_apply_to_live_score` 를 `True`로 머지하지 않는다 (kill switch 무력화 금지)
- ❌ A1/A2 broker accounting audit gates 가 모두 `passed=True`가 되기 전에 production weight를 promote 하지 않는다
- ❌ `master` 브랜치에 직접 push 하지 않는다 — 모든 작업은 feature branch + PR
- ❌ Hardcoded tickers (예: CLSK, T1 Energy)를 production 코드에 넣지 않는다 — 학습 데이터로만 사용
- ❌ `report_period`를 PIT availability 기준으로 사용하지 않는다 — 반드시 `accepted_at_ts` / `available_from_ts`
- ❌ ETF holdings의 정적 lookthrough (`ETF_LOOKTHROUGH` constant)를 PIT evidence로 신뢰하지 않는다 — Phase C5 PIT 데이터 필요
- ❌ 6개월 SHIP verdict 연속 통과 + 사람 승인 전에 `Phase C8 Full Auto promotion` 실행 안 한다
- ❌ Auto-merge PR을 만들 때 `--no-verify` 또는 hook skip 사용 금지

---

## 3. Verified Code State (2026-05-20, master 기준)

Codex가 이 사실을 출발점으로 삼아야 한다. 모두 직접 코드 검증 완료:

| 사실 | 위치 | 검증 |
|---|---|:-:|
| `w_sec_institutional_evidence = 0.30` (default) | `r1000_config.py:2103` | ✅ |
| `w_sec_insider_evidence = 0.20` (default) | `r1000_config.py:2104` | ✅ |
| SEC overlay가 score에 **무조건 가산** (master switch 없음) | `r1000_pipeline.py:1098-1108` | ✅ |
| `manager_alpha()` 함수 존재 (single horizon) | `tools/run_sec_evidence_signal_audit.py:207-276` | ✅ |
| `forward_return()` 함수 존재 (30/60/90/180d) | `r1000_rule_backtester.py:80-88` | ✅ |
| 13F position deltas + new_position 플래그 존재 | `tools/run_sec_institutional_signals.py:70` (`add_13f_position_deltas`) | ✅ |
| 13F PIT 컬럼 (`accepted_at_ts`, `available_from_ts`) 존재 | `tools/run_sec_institutional_signals.py:prepare_13f_holdings()` | ✅ |
| `ETF_LOOKTHROUGH` static constant | `tools/run_theme_leadership_tape.py` | ✅ |
| broker_accounting_audit A1/A2 모두 `passed=None` (실패) | `research/broker_accounting_audit.json` | ✅ |
| 34 managers verified | `managers.csv` (master, fb64215 이후) | ✅ |
| SEC 13F + Form 4 데이터 미존재 (cron 미실행) | `outputs/sec_institutional_signals/` 비어있음 | ✅ |

→ Codex는 이 facts를 prompt 또는 task spec에 그대로 복사해서 사용할 것.

---

## 4. Branch Strategy

### 4.1 Branch Topology

```
master
  │
  ├─ codex/plan-c-foundation         ← Phase C0.1 (KILL SWITCH) + C0.2 (governance)
  │       │  small PR, BLOCKING merge first
  │       │
  │       ├─ codex/plan-c-d1-13f-events       ← Phase D1
  │       ├─ codex/plan-c-d5-form4-pcode      ← Phase D5
  │       ├─ codex/plan-c-d7-13d-activist     ← Phase D7
  │       │
  │       └─ codex/plan-c-d2-d3-labels-scores ← Phase D2 + D3 (depends on D1/D5/D7 merge)
  │
  ├─ codex/plan-c-broker-a1-a2-fix    ← INDEPENDENT track (A1/A2 fix, runs in parallel)
  │       │  must merge before any production weight promotion
  │
  ├─ codex/plan-c-d4-live-scoring     ← Phase D4 (depends on D2/D3 merged)
  ├─ codex/plan-c-d6-follow-fade      ← Phase D6 (depends on D2/D3 merged, can run with D4)
  │
  ├─ codex/plan-c-c4-broker-challenger ← Phase C4 (depends on D4 + D6 merged)
  │
  ├─ codex/plan-c-c5-etf-pit          ← Phase C5 (INDEPENDENT, can start any time after foundation)
  ├─ codex/plan-c-c6-top30-watchlist  ← Phase C6 (depends on D4 merged)
  ├─ codex/plan-c-c7-after-service    ← Phase C7 (depends on D4 merged)
  │
  └─ codex/plan-c-c8-c9-promotion     ← BLOCKED until A1/A2 pass + 6mo SHIP verdict
```

### 4.2 Branch Naming Convention

```
codex/plan-c-<phase>-<short-description>
```

Examples:
- `codex/plan-c-foundation` (Phase C0.1 + C0.2)
- `codex/plan-c-d1-13f-events`
- `codex/plan-c-d2-d3-labels-scores`
- `codex/plan-c-c4-broker-challenger`

### 4.3 Branch base policy

| Branch | Base from | Reason |
|---|---|---|
| `codex/plan-c-foundation` | `master` | small, isolated, must merge first |
| `codex/plan-c-d1-*`, `d5-*`, `d7-*` | `codex/plan-c-foundation` (after merge to master, rebase to master) | needs kill switch in place |
| `codex/plan-c-d2-d3-*` | merge of d1+d5+d7 into master | needs event parquets to label |
| `codex/plan-c-broker-a1-a2-fix` | `master` | fully independent |
| `codex/plan-c-c5-etf-pit` | `master` | independent ETF infrastructure |
| `codex/plan-c-d4-*` | d2-d3 merged | needs manager_pda_scores.parquet |
| `codex/plan-c-c4-*` | d4 + d6 merged | needs all 4 streams |
| `codex/plan-c-c6-*`, `c7-*` | d4 merged | needs live PDA scoring |
| `codex/plan-c-c8-c9-*` | broker-a1-a2 merged + 6mo data | promotion gates |

### 4.4 Conflict Resolution Policy

- **Foundation branch is master.** All feature branches rebase onto foundation before merge.
- If two feature branches modify the same file (e.g., D1 and D5 both touch `r1000_features.py`), the later-to-merge branch rebases and resolves locally.
- Plan C 문서들 (`PLAN_C_V3_5_*.md`, `CODEX_HANDOFF_*.md`) 은 foundation에 한 번 머지 후 read-only로 취급. 추가 결정은 별도 `research/plan_c_decisions_log.md` 에 기록.

---

## 5. Phase 상세 명세

### Phase C0.1 — KILL SWITCH (BLOCKING #1)

**Branch**: `codex/plan-c-foundation` (base: master)
**Effort**: 2-4시간
**Dependency**: 없음
**Why first**: SEC overlay가 현재 score에 무조건 가산됨. Kill switch 없이 SEC 데이터 트리거 시 ranking 즉시 변경됨.

#### 5.1.1 변경할 파일

##### `r1000_config.py` — line 2104 다음에 추가

```python
    w_sec_insider_evidence: float = 0.20
    # ── Plan C v3.5 (2026-05-20) — Master kill switches for SEC + PDA overlays.
    # Both default OFF; codex/plan-c-foundation merge does NOT change production behavior.
    # Flip to True only after: (1) Phase C1 data lands, (2) Phase C1.5 readiness audit
    # passes, (3) Phase C4 broker-ledger challenger verifies SHIP gate.
    sec_evidence_apply_to_live_score: bool = False
    sec_evidence_bonus_cap: float = 0.20
    sec_evidence_min_form4_signal_tickers: int = 300
    sec_evidence_min_13f_signal_tickers: int = 100
    sec_evidence_max_stale_days: int = 240
    # PDA (Post-Disclosure Alpha) framework — Phase D wiring.
    pda_apply_to_live_score: bool = False
    pda_bonus_cap: float = 0.15
    w_pda_13f: float = 0.0          # learned via Phase D3
    w_pda_form4: float = 0.0        # learned via Phase D3
    w_pda_13d: float = 0.0          # learned via Phase D3
    w_pda_etf: float = 0.0          # learned via Phase D3 (depends on Phase C5)
```

##### `r1000_pipeline.py` — line 1098-1108 교체

**현재 (master)**:
```python
    d["score_sec_institutional_overlay"] = (
        w_inst * inst_score * inst_conf.clip(lower=0.0, upper=1.0)
    ).fillna(0.0)
    d["score_sec_insider_overlay"] = (
        w_insider * insider_score * insider_conf.clip(lower=0.0, upper=1.0)
    ).fillna(0.0)
    d["score"] = (
        d["score"]
        + d["score_sec_institutional_overlay"]
        + d["score_sec_insider_overlay"]
    )
    return d
```

**Phase C0.1 변경**:
```python
    d["score_sec_institutional_overlay"] = (
        w_inst * inst_score * inst_conf.clip(lower=0.0, upper=1.0)
    ).fillna(0.0)
    d["score_sec_insider_overlay"] = (
        w_insider * insider_score * insider_conf.clip(lower=0.0, upper=1.0)
    ).fillna(0.0)
    # Plan C v3.5 kill switch: overlay columns are populated for diagnostics +
    # downstream shadow studies, but never added to live score unless the master
    # switch is explicitly flipped. Cap protects against runaway weights.
    if bool(getattr(cfg, "sec_evidence_apply_to_live_score", False)):
        cap = float(getattr(cfg, "sec_evidence_bonus_cap", 0.20))
        sec_bonus = (
            d["score_sec_institutional_overlay"]
            + d["score_sec_insider_overlay"]
        ).clip(upper=cap * d["score"].abs())
        d["score"] = d["score"] + sec_bonus
    return d
```

##### `tests/smoke_test.py` — 새 테스트 4개 추가

기존 `@_test` 블록 패턴 따라:

```python
@_test
def plan_c_v3_5_kill_switch_defaults_off():
    """Plan C v3.5 — both master switches must default to OFF."""
    from r1000_config import EngineConfig
    cfg = EngineConfig()
    assert cfg.sec_evidence_apply_to_live_score is False, (
        "sec_evidence_apply_to_live_score must default OFF — see CODEX_HANDOFF Phase C0.1"
    )
    assert cfg.pda_apply_to_live_score is False, (
        "pda_apply_to_live_score must default OFF"
    )

@_test
def plan_c_v3_5_kill_switch_blocks_overlay():
    """Plan C v3.5 — SEC overlay must NOT enter score when switch is OFF."""
    import pandas as pd
    from r1000_config import EngineConfig
    from r1000_pipeline import add_total_score_columns
    df = pd.DataFrame({
        "score": [1.0, 1.0],
        "institutional_evidence_score": [0.8, 0.0],
        "institutional_evidence_confidence_score": [1.0, 0.0],
        "early_evidence_score": [0.5, 0.0],
        "evidence_confidence_score": [1.0, 0.0],
    })
    cfg = EngineConfig(sec_evidence_apply_to_live_score=False)
    result = add_total_score_columns(df, cfg)
    # Score did NOT change despite non-zero overlay
    assert abs(result["score"].iloc[0] - 1.0) < 1e-9
    # But overlay columns are still computed for diagnostics
    assert result["score_sec_institutional_overlay"].iloc[0] > 0.0

@_test
def plan_c_v3_5_overlay_applied_when_switch_on():
    """Plan C v3.5 — when switch ON, overlay is applied with cap."""
    import pandas as pd
    from r1000_config import EngineConfig
    from r1000_pipeline import add_total_score_columns
    df = pd.DataFrame({
        "score": [1.0],
        "institutional_evidence_score": [0.8],
        "institutional_evidence_confidence_score": [1.0],
        "early_evidence_score": [0.5],
        "evidence_confidence_score": [1.0],
    })
    cfg = EngineConfig(
        sec_evidence_apply_to_live_score=True,
        sec_evidence_bonus_cap=0.20,
        w_sec_institutional_evidence=0.30,
        w_sec_insider_evidence=0.20,
    )
    result = add_total_score_columns(df, cfg)
    # Expected raw bonus = 0.30*0.8*1.0 + 0.20*0.5*1.0 = 0.34
    # Capped at 0.20 * |1.0| = 0.20
    assert result["score"].iloc[0] <= 1.0 + 0.20 + 1e-6

@_test
def plan_c_v3_5_pda_weights_default_zero():
    """Plan C v3.5 — PDA weights start at 0, learned via Phase D3."""
    from r1000_config import EngineConfig
    cfg = EngineConfig()
    assert cfg.w_pda_13f == 0.0
    assert cfg.w_pda_form4 == 0.0
    assert cfg.w_pda_13d == 0.0
    assert cfg.w_pda_etf == 0.0
```

#### 5.1.2 Verification Gate

- `py -3 tests/smoke_test.py` → 모든 기존 + 4 신규 통과
- `py -3 run_local.py --verdict-only` → CAGR / MaxDD / Sharpe **변경 없음** (kill switch off이므로)
- Diff inspection: 변경된 파일 3개만 (`r1000_config.py`, `r1000_pipeline.py`, `tests/smoke_test.py`)

#### 5.1.3 PR Template

```markdown
## Plan C v3.5 — Phase C0.1: Kill Switch for SEC + PDA overlays

### Why
Per CODEX_HANDOFF_PLAN_C_V3_5 §5.1, the SEC evidence overlay at
r1000_pipeline.py:1098-1108 unconditionally adds bonus to score. This must
be gated by a master switch before Phase C1 (SEC data trigger) so the
trigger does not silently change ranking.

### What
- r1000_config.py: 4 SEC switches + 5 PDA weight fields (all OFF/zero by default)
- r1000_pipeline.py: gate overlay addition with `cfg.sec_evidence_apply_to_live_score`
- tests/smoke_test.py: 4 new tests verifying off-by-default behavior

### Production impact
ZERO. All switches default OFF. Running `r1000_pipeline.run_full(cfg)` with
default config produces byte-identical outputs to master.

### Verification
- [x] tests/smoke_test.py passes (4 new tests)
- [x] run_local.py --verdict-only matches baseline ±0.01%
- [x] Diff scope: 3 files only

### Linked plan
/root/.claude/plans/elegant-sniffing-dragon.md Part F (v3.5)
CODEX_HANDOFF_PLAN_C_V3_5_20260520.md §5.1
```

#### 5.1.4 Merge Policy

- CI 통과 + 1 human review approval 후 머지
- 머지 후 모든 다른 PDA branch가 이 base에서 rebase 됨

---

### Phase D1 — 13F Event Builder

**Branch**: `codex/plan-c-d1-13f-events` (base: codex/plan-c-foundation post-merge)
**Effort**: 1-2일
**Dependency**: Phase C0.1 merged. **SEC 데이터 없어도 골격 작성 가능**.

#### 5.2.1 NEW file: `tools/run_13f_position_event_builder.py`

**Input**:
- `data_pit/sec/institutional_13f_holdings.parquet` (PIT) — 없으면 빈 출력 + warning
- `cache_prices/*.parquet` — 시장가 (이미 존재)

**Output**: `data_pit/sec/13f_position_events.parquet`

**Schema**:
```python
{
    # Identity
    "event_id": str,                  # UUID
    "manager_cik": str,
    "manager_name": str,
    "issuer_cik": str,
    "ticker": str,                    # normalized
    "filing_accession_number": str,

    # Timing (PIT critical)
    "filing_date": date,              # reported filing date
    "report_period": date,            # 13F period end (NEVER use as availability)
    "accepted_at_ts": datetime,       # SEC acceptance timestamp
    "available_from_ts": datetime,    # earliest tradable timestamp
    "next_close_after_available": datetime,  # for return labeling

    # Event type
    "position_type": str,             # new / increased / decreased / closed / unchanged
    "shares_current": int,
    "shares_previous": int,
    "shares_delta": int,
    "shares_delta_pct": float,        # NaN for new

    # Manager portfolio context
    "manager_aum_usd": float,
    "manager_aum_bucket": str,        # micro/small/mid/large/mega
    "manager_holdings_count_current": int,
    "position_size_pct_of_manager_aum": float,
    "position_size_pct_added_to_aum": float,  # for new/increased

    # Issuer context
    "issuer_market_cap_usd": float,
    "issuer_market_cap_bucket": str,  # micro/small/mid/large/mega
    "issuer_float_shares": int,
    "issuer_float_pct_owned": float,            # ChatGPT v3.5 NEW
    "issuer_float_pct_added": float,            # ChatGPT v3.5 NEW
    "industry": str,                  # mapped from r1000_features
    "gics_sector": str,

    # Aggregation hints (filled by D3, not D1)
    "manager_count_for_ticker": int,            # how many other managers hold this
    "convergence_window_30d": bool,             # multiple managers within 30d window
}
```

**PIT discipline (CRITICAL)**:
- `available_from_ts = accepted_at_ts + processing_lag` (where processing_lag = 1 trading day)
- All forward-looking joins use `available_from_ts` (never `filing_date` or `report_period`)
- Embargo: events within 126 trading days of `as_of_date` (caller param) are dropped

#### 5.2.2 Helper integration

- Reuse `tools/run_sec_institutional_signals.py:add_13f_position_deltas()` for delta computation
- Reuse `tools/run_sec_institutional_signals.py:prepare_13f_holdings()` for PIT timestamps

#### 5.2.3 Tests

```python
@_test
def d1_event_builder_pit_discipline():
    """Phase D1 — available_from_ts MUST NOT be earlier than accepted_at_ts."""
    # Synthetic 13F input
    # Run builder
    # Assert all rows: available_from_ts >= accepted_at_ts

@_test
def d1_event_builder_position_type_complete():
    """Phase D1 — every event must have non-null position_type."""

@_test
def d1_event_builder_issuer_float_pct_in_range():
    """Phase D1 — issuer_float_pct_owned in [0, 100]."""
```

#### 5.2.4 Verification Gate

- 골격 코드 + 3 smoke tests 통과
- 가짜 데이터 (`tests/fixtures/synthetic_13f.parquet`) 1개 만들어서 회귀 테스트
- Phase D2 가 이 schema를 그대로 소비할 수 있어야 함

---

### Phase D5 — Form 4 P-Code Filtered Event Builder

**Branch**: `codex/plan-c-d5-form4-pcode` (base: codex/plan-c-foundation, parallel to D1)
**Effort**: 1일

#### 5.3.1 NEW file: `tools/run_form4_filtered_event_builder.py`

**Filter logic (ChatGPT v3.5 critical)**:
```python
CONVICTION_CODES = {"P"}              # open-market buys only (signal)
SOFT_RISK_CODES = {"S"}                # open-market sales (weak negative signal)
EXCLUDE_CODES = {"M", "A", "F", "D", "G", "C"}   # option/award/tax/gift noise
# M = exercise of options
# A = grant/award
# F = payment of exercise price by withholding shares
# D = distribution
# G = gift
# C = conversion
```

**Output**: `data_pit/sec/form4_filtered_events.parquet`

**Schema**:
```python
{
    "event_id": str,
    "insider_cik": str,
    "insider_name": str,
    "insider_role": str,              # CEO / CFO / Director / Officer / 10pct_owner
    "issuer_cik": str,
    "ticker": str,
    "accepted_at_ts": datetime,
    "available_from_ts": datetime,
    "transaction_code": str,          # P only retained (or S for separate fade analysis)
    "transaction_date": date,
    "shares": int,
    "price_per_share": float,
    "total_value_usd": float,
    "insider_holdings_post_tx": int,
    "insider_holdings_pct_of_issuer": float,
    # Cluster detection (computed in same pass)
    "cluster_buy_flag": bool,         # 2+ insiders within 30d
    "cluster_size": int,              # count of insiders in cluster
    "cluster_total_value_usd": float,
    "is_first_in_cluster": bool,      # first filer in cluster window
}
```

#### 5.3.2 Cluster detection algorithm

```python
def detect_clusters(events: pd.DataFrame, window_days: int = 30) -> pd.DataFrame:
    """For each (ticker, insider_role), flag if 2+ different insiders bought within 30d.
    Uses available_from_ts (PIT safe)."""
    events = events.sort_values(["ticker", "available_from_ts"])
    for ticker, group in events.groupby("ticker"):
        # For each event, count distinct insider_ciks within preceding 30d
        # Flag cluster_buy_flag = (distinct_count >= 2)
```

#### 5.3.3 Tests

```python
@_test
def d5_form4_filters_only_p_code():
    """Phase D5 — only P transactions retained for conviction stream."""

@_test
def d5_form4_excludes_m_a_f_d_g_c():
    """Phase D5 — exclusion codes never appear in conviction output."""

@_test
def d5_form4_cluster_detection_30d_window():
    """Phase D5 — 2+ insiders within 30d trigger cluster_buy_flag=True."""
```

---

### Phase D7 — 13D Activist Event Collector (NEW v3.5)

**Branch**: `codex/plan-c-d7-13d-activist` (base: codex/plan-c-foundation, parallel)
**Effort**: 1-2일

#### 5.4.1 NEW file: `tools/run_13d_activist_event_collector.py`

**Data source**: SEC EDGAR 13D + 13D/A (amendments) filings via `https://www.sec.gov/cgi-bin/browse-edgar`.

**Output**: `data_pit/sec/13d_events.parquet`

**Schema**:
```python
{
    "event_id": str,
    "filer_cik": str,
    "filer_name": str,
    "filer_type": str,                # individual / hedge_fund / private_equity / activist_fund
    "issuer_cik": str,
    "ticker": str,
    "filing_date": date,
    "accepted_at_ts": datetime,
    "available_from_ts": datetime,
    "filing_type": str,               # SC 13D / SC 13D/A
    "is_amendment": bool,
    "amendment_number": int,
    # Position
    "shares_owned": int,
    "ownership_pct": float,           # 5% / 10% / 15%+
    "ownership_pct_delta": float,     # from prior 13D/A
    # Intent classification (parsed from Item 4)
    "intent_category": str,           # control / influence / passive / unknown
    "intent_keywords": list[str],     # ["board representation", "strategic alternatives", ...]
    "activist_filer_flag": bool,      # filer in known activist list
    # Context
    "issuer_market_cap_usd": float,
    "issuer_market_cap_bucket": str,
}
```

#### 5.4.2 Known activist tracker

NEW config: `research/known_activists.yaml`
```yaml
known_activists:
  - {cik: "0000949509", name: "Icahn Carl C", tier: "tier1"}
  - {cik: "0001336528", name: "Pershing Square Capital Management", tier: "tier1"}
  - {cik: "0001047949", name: "Elliott Investment Management", tier: "tier1"}
  - {cik: "0001418814", name: "ValueAct Capital Management", tier: "tier1"}
  - {cik: "0001517137", name: "Starboard Value LP", tier: "tier1"}
  - {cik: "0001478735", name: "Trian Fund Management", tier: "tier2"}
  - {cik: "0001040273", name: "Third Point LLC", tier: "tier2"}
  - {cik: "0001403528", name: "Engaged Capital LLC", tier: "tier2"}
  - {cik: "0001580560", name: "Land & Buildings Investment", tier: "tier3"}
  # ... up to ~30 historically-validated activist filers
```

Codex가 직접 검증된 CIK 추가하지 말 것 — 별도 human review PR로 yaml 업데이트.

#### 5.4.3 Tests

```python
@_test
def d7_13d_parser_handles_amendment_chain():
    """Phase D7 — amendments are linked to original 13D filer + issuer."""

@_test
def d7_13d_intent_classification():
    """Phase D7 — Item 4 text keywords map to intent_category correctly."""
```

---

### Phase D2 — Post-Disclosure Alpha Labeler

**Branch**: `codex/plan-c-d2-d3-labels-scores` (base: master post-merge of D1+D5+D7)
**Effort**: 1-2일

#### 5.5.1 NEW file: `tools/run_post_disclosure_alpha_labeler.py`

**Input**:
- `data_pit/sec/13f_position_events.parquet` (Phase D1)
- `data_pit/sec/form4_filtered_events.parquet` (Phase D5)
- `data_pit/sec/13d_events.parquet` (Phase D7)
- `cache_prices/*.parquet` (8년 가격)

**Output**: `data_pit/sec/post_disclosure_alpha_labels.parquet`

**Schema**:
```python
{
    "event_id": str,                  # FK to source event
    "source_stream": str,             # 13f / form4 / 13d
    "ticker": str,
    "available_from_ts": datetime,
    "entry_close_ts": datetime,       # first close AFTER available_from_ts
    "entry_price": float,
    # Forward returns (multi-horizon)
    "ret_1d": float,
    "ret_5d": float,
    "ret_21d": float,                 # ChatGPT 21-day study window
    "ret_42d": float,                 # ChatGPT 42-day study window
    "ret_63d": float,
    "ret_126d": float,
    # SPY excess returns
    "excess_spy_1d": float,
    "excess_spy_5d": float,
    "excess_spy_21d": float,
    "excess_spy_42d": float,
    "excess_spy_63d": float,
    "excess_spy_126d": float,
    # Hit flags
    "hit_21d": bool,                  # ret_21d > 0
    "hit_63d": bool,
    "hit_excess_21d": bool,           # excess_spy_21d > 0
    "explosive_hit_63d": bool,        # ret_63d > 0.30
    # Drawdown during holding period
    "max_drawdown_21d": float,
    "max_drawdown_63d": float,
}
```

**Critical PIT rule**: `entry_close_ts` is the **first market close AFTER** `available_from_ts`. Never use intraday or same-day prices.

#### 5.5.2 Verification

- All labels for events with `available_from_ts > T` are zero/null when computed at time T (walk-forward safety)
- Test fixture: 5 hand-validated events with known returns

---

### Phase D3 — Multi-Bucket Manager / Insider / Activist PDA Scoring

**Branch**: `codex/plan-c-d2-d3-labels-scores` (same branch as D2)
**Effort**: 2-3일

#### 5.6.1 NEW file: `tools/run_manager_disclosure_alpha_scoring.py`

**Input**: D2 labels parquet
**Output**: `data_pit/sec/manager_pda_scores.parquet`

**Bucket dimensions**:
- `market_cap_bucket`: micro / small / mid / large / mega
- `position_type`: new / increased / decreased / closed
- `gics_sector`: technology / healthcare / energy / financials / consumer / industrials / utilities / materials / real_estate / communication / staples
- `recency`: recent_1y / recent_3y / all_time

**Schema (manager × bucket × as_of_date)**:
```python
{
    "manager_cik": str,
    "as_of_date": date,               # walk-forward cut date
    "market_cap_bucket": str,
    "position_type": str,
    "gics_sector": str,
    "recency": str,
    # Sample
    "obs_count": int,
    "first_event_date": date,
    "last_event_date": date,
    # Returns (mean, hit rate, median)
    "avg_ret_21d": float,
    "avg_ret_42d": float,
    "avg_ret_63d": float,
    "avg_ret_126d": float,
    "avg_excess_21d": float,
    "avg_excess_42d": float,
    "avg_excess_63d": float,
    "avg_excess_126d": float,
    "hit_rate_excess_21d": float,
    "hit_rate_excess_63d": float,
    "explosive_hit_rate_63d": float,
    # Composite
    "pda_composite_score": float,     # [0, 1] normalized
    "pda_confidence": float,          # min(obs_count / 50, 1.0)
}
```

#### 5.6.2 NEW files for Form 4 + 13D

- `tools/run_insider_disclosure_alpha_scoring.py` → `insider_pda_scores.parquet` (insider × role × cluster_flag × bucket)
- `tools/run_activist_disclosure_alpha_scoring.py` → `activist_pda_scores.parquet` (filer × intent × ownership_pct_band)

#### 5.6.3 Walk-forward discipline

- `as_of_date` 이전 데이터만 사용
- 매 분기 (Mar 31, Jun 30, Sep 30, Dec 31) snapshot 생성
- 가장 최근 `as_of_date` 의 점수만 Phase D4가 live scoring에 사용

---

### Phase D6 — FOLLOW vs FADE Validation

**Branch**: `codex/plan-c-d6-follow-fade` (parallel to D4)
**Effort**: 1-2일

#### 5.7.1 NEW file: `tools/run_follow_vs_fade_validation.py`

**Hypotheses to test**:

| ID | Stream | Direction | Hypothesis |
|---|---|---|---|
| H1 | 13F | FOLLOW | High-PDA manager new buy → outperform 21-63d |
| H2 | 13F | FADE | 15+ manager already holding + low new ratio → underperform (crowded) |
| H3 | Form4 | FOLLOW | Cluster buy (2+ insiders, P only) → outperform 21d |
| H4 | Form4 | FOLLOW | CEO+CFO same-week buy → outperform 63d |
| H5 | 13F | FADE | Low-PDA manager copying high-PDA manager 1Q late → underperform |
| H6 | 13D | FOLLOW | Tier1 activist new 13D → outperform 63d |
| H7 | 13F | FOLLOW | issuer_float_pct_added > 1% → outperform (CLSK pattern) |

**Output**: `outputs/post_disclosure_signal_learning/follow_vs_fade_report.csv`

Each hypothesis tested with:
- IC (Spearman) of signal vs forward return
- t-stat (n>30)
- Decile spread (top vs bottom)
- Walk-forward stability (rolling 18mo IC)

#### 5.7.2 Academic citation

Cite in commit message: "13F imbalance research suggests 21-42 trading day window is most significant for institutional disclosure alpha decay."

---

### Phase D4 — Live PDA Scoring (4-Stream Application)

**Branch**: `codex/plan-c-d4-live-scoring` (base: master post-merge of D2+D3+D6)
**Effort**: 2-3일

#### 5.8.1 New function in `r1000_features.py`

```python
def compute_ticker_pda_score_v3_5(
    ticker: str,
    as_of_date: pd.Timestamp,
    recent_13f_events: pd.DataFrame,
    recent_form4_events: pd.DataFrame,
    recent_13d_events: pd.DataFrame,
    manager_pda_scores: pd.DataFrame,
    insider_pda_scores: pd.DataFrame,
    activist_pda_scores: pd.DataFrame,
    lookback_days: int = 90,
) -> dict:
    """
    Compute live PDA scores for ticker as of as_of_date.

    Returns dict with:
      - post_13f_alpha_score, post_13f_alpha_confidence
      - post_form4_alpha_score, post_form4_alpha_confidence
      - post_13d_alpha_score, post_13d_alpha_confidence
      - pda_convergence_flag (>= 2 streams > 0.65)
      - pda_total_score (weighted sum, NOT yet applied to live score)
    """
```

Formula per Plan F.1:
```python
post_13f_alpha_score = (
    0.22 * manager_pda_score_bucketed
  + 0.18 * event_strength_score
  + 0.16 * issuer_float_impact_score
  + 0.14 * multi_manager_convergence
  + 0.10 * post_filing_price_confirmation
  + 0.08 * smallcap_discovery_score
  + 0.07 * sector_theme_fit
  + 0.05 * crowded_trade_penalty
)
# (and similar for Form4, 13D streams)
```

#### 5.8.2 Wire into `r1000_pipeline.py` (BEHIND kill switch)

After SEC overlay block (post-line 1108), add:

```python
    # Plan C v3.5 Phase D4 — Post-disclosure alpha (4-stream) overlay.
    # Computed for all rows for diagnostics; applied to score ONLY if kill switch ON.
    pda_13f = numeric_series_or_default(d, "post_13f_alpha_score", 0.0)
    pda_form4 = numeric_series_or_default(d, "post_form4_alpha_score", 0.0)
    pda_13d = numeric_series_or_default(d, "post_13d_alpha_score", 0.0)
    pda_etf = numeric_series_or_default(d, "post_etf_alpha_score", 0.0)
    convergence_bonus = numeric_series_or_default(d, "pda_convergence_bonus", 0.0)
    d["pda_total_score"] = (
        cfg.w_pda_13f * pda_13f
        + cfg.w_pda_form4 * pda_form4
        + cfg.w_pda_13d * pda_13d
        + cfg.w_pda_etf * pda_etf
        + convergence_bonus
    )
    if bool(getattr(cfg, "pda_apply_to_live_score", False)):
        cap = float(getattr(cfg, "pda_bonus_cap", 0.15))
        pda_bonus = d["pda_total_score"].clip(upper=cap * d["score"].abs())
        d["score"] = d["score"] + pda_bonus
    return d
```

#### 5.8.3 Verification

- Kill switch off → score 무변경 (회귀 테스트)
- Kill switch on + 합성 데이터 → 예상 PDA bonus가 score에 가산
- Phase C4 broker challenger 에서 8 scenario 측정 가능 (kill switch 토글로)

---

### Phase C4 — Broker-Ledger Challenger (Validation)

**Branch**: `codex/plan-c-c4-broker-challenger` (base: master post-merge D4 + D6)
**Effort**: 2-3일

#### 5.9.1 NEW file: `tools/run_evidence_overlay_challenger.py`

Reuse existing `tools/auto_policy_challenger.py` infrastructure for harness.

**8 scenarios**:

| Scenario | sec_evidence_apply | pda_apply | w_pda_13f | w_pda_form4 | w_pda_13d | Convergence | Notes |
|---|:-:|:-:|---|---|---|:-:|---|
| A baseline | OFF | OFF | 0 | 0 | 0 | — | current production |
| B 13F only | OFF | ON | 0.06 | 0 | 0 | — | isolated 13F |
| C Form4 only | OFF | ON | 0 | 0.04 | 0 | — | isolated Form4 |
| D 13D only | OFF | ON | 0 | 0 | 0.04 | — | isolated 13D |
| E SEC legacy | ON | OFF | 0 | 0 | 0 | — | PR #16 overlay only |
| F PDA additive | OFF | ON | 0.06 | 0.04 | 0.04 | OFF | 3-stream sum |
| G PDA + conv | OFF | ON | 0.06 | 0.04 | 0.04 | ON | convergence bonus on |
| H Full | ON | ON | 0.06 | 0.04 | 0.04 | ON | everything |

**SHIP gate (vs A baseline)**:
- dCAGR ≥ +1.5pp on main, ≥ +2pp on concentrated
- dSharpe ≥ -0.05
- dMaxDD ≥ -3pp
- early_scout count ≥ 4
- Cost sensitivity OK at 25/50/75/100 bps

#### 5.9.2 Output

`outputs/evidence_overlay_challenger/scenario_matrix.csv` + `verdict.json`

---

### Phase C5 — ETF PIT Holdings

**Branch**: `codex/plan-c-c5-etf-pit` (INDEPENDENT, can start anytime after foundation)
**Effort**: 3-5일

#### 5.10.1 NEW directory: `data_pit/etf/`

`data_pit/etf/etf_holdings_pit.parquet`:
```python
{
    "etf_ticker": str,
    "underlying_ticker": str,
    "as_of_date": date,               # holdings published date
    "available_from_ts": datetime,    # NEXT business day after publication
    "weight_pct": float,
    "shares_held": int,
    "is_new_inclusion": bool,         # not in prior snapshot
}
```

**Source**: ETF issuer websites (iShares, SPDR, ARK, etc.) or third-party (etfdb, etf.com).
Initial coverage: 17 sector ETFs + 8 thematic = 25 ETFs daily snapshots.

#### 5.10.2 Replace static `ETF_LOOKTHROUGH`

Modify `tools/run_theme_leadership_tape.py` to load PIT holdings instead of static constant.

#### 5.10.3 Wire into Phase D2 labeler

Add ETF inclusion as 4th event stream:
- `data_pit/sec/etf_inclusion_events.parquet`
- Each new_inclusion → forward return label

---

### Phase C6 — Smart Money Top30 Standalone

**Branch**: `codex/plan-c-c6-top30-watchlist` (base: master post-merge D4)
**Effort**: 2-3일

#### 5.11.1 NEW file: `tools/run_smart_money_top30.py`

**Output**: `outputs/smart_money/top30_latest.csv` (daily, 09:00 KST cron)

**Score (NOT tied to main portfolio score)**:
```python
composite_smart_money_score = (
    0.30 * post_13f_alpha_score
  + 0.25 * post_form4_alpha_score
  + 0.20 * post_13d_alpha_score
  + 0.15 * post_etf_alpha_score
  + 0.10 * pda_convergence_score
) * 100  # 0-100 scale
```

**Schema**:
```python
{
    "rank": int,
    "ticker": str,
    "company": str,
    "industry": str,
    "gics_sector": str,
    "composite_smart_money_score": float,    # 0-100
    "post_13f_alpha_score": float,
    "manager_count": int,
    "top_3_managers": str,                   # comma-separated
    "post_form4_alpha_score": float,
    "cluster_buy_flag": bool,
    "ceo_cfo_buy_flag": bool,
    "post_13d_alpha_score": float,
    "activist_filer": str,                   # if any
    "post_etf_alpha_score": float,
    "leading_etfs_list": str,                # comma-separated
    "convergence_flag": bool,
    "days_since_first_signal": int,
    "explanation_text": str,                 # templated NL
}
```

#### 5.11.2 NEW workflow: `.github/workflows/smart_money_top30_daily.yml`

Daily cron 09:00 KST → run tool → commit CSV → optional Telegram push.

---

### Phase C7 — After-Service Infrastructure

**Branch**: `codex/plan-c-c7-after-service` (parallel to C6)
**Effort**: 3-4일

#### 5.12.1 NEW files

- `tools/run_anomaly_monitor.py` (daily)
- `tools/run_signal_lifecycle.py` (quarterly auto-retire/promote)
- `tools/run_baseline_proposal.py` (after SHIP verdict, draft PR)
- `tools/run_regime_drift_detection.py` (monthly)
- `research/auto_signal_status.yaml` (tracker)

#### 5.12.2 NEW workflows

- `.github/workflows/anomaly_monitor.yml` (daily)
- `.github/workflows/signal_lifecycle.yml` (quarterly)
- `.github/workflows/auto_baseline_proposal.yml` (post-SHIP, manual approval)

#### 5.12.3 Alert criteria

- `avg_cash_weight > 25%` for 2 consecutive months
- `position_risk_exit_count > 50/month`
- 12mo rolling CAGR vs 8y average drift > 5pp
- `early_scout_count < 4` for 2 months

---

### Phase C8 — Full Auto Weight Promotion (BLOCKED initially)

**Branch**: `codex/plan-c-c8-c9-promotion` — **DO NOT MERGE** until:
1. A1/A2 broker accounting audit gates both `passed=True`
2. 6 months of consecutive SHIP verdicts via C4 challenger
3. Explicit human approval recorded in `research/plan_c_decisions_log.md`

**Mechanism**:
- Quarterly cron reads `outputs/sec_evidence_learning/best_score_weights.json`
- Calls `tools/auto_policy_challenger.py` for validation
- Auto-creates PR with weight diff
- Auto-merges only if: CI green AND hard gates pass AND max delta ≤ 30% per weight per quarter AND no `[skip-auto-promote]` flag

**Safety**:
- Rollback trigger: dCAGR < -1pp next month → auto-revert + 30d lock
- Manual override: `[skip-auto-promote]` in any commit blocks 30d

---

### Phase C9 — Regime Multiplier Calibration

**Branch**: `codex/plan-c-c8-c9-promotion` (same as C8, blocked together)

NEW: `tools/run_regime_multiplier_calibrate.py`
- Quarterly recalibrate 5×7 multiplier table
- Output: `research/regime_weight_multipliers_YYYY-Q.yaml`
- Auto-PR if shift > 0.1 in any cell

---

## 6. Independent Track: A1/A2 Broker Accounting Fix

**Branch**: `codex/plan-c-broker-a1-a2-fix` (FULLY INDEPENDENT, can run from day 1)
**Effort**: 3-5일

#### 6.1 Two failing gates

| Gate | Field | Description | File |
|---|---|---|---|
| A1 | `delisted_cost_basis_fallback_eliminated` | When delisted ticker has no entry close, system silently uses fallback | `r1000_broker_replay.py` / `tools/run_broker_accounting_audit.py` |
| A2 | `survivorship_coverage_audited` | Universe used in backtest does not include delisted-before-now R1000 names | `aggressive/universe.py:191-220` |

#### 6.2 Fix A1

- Detect delisted tickers in price cache
- Use last-known close before delisting + corporate action adjustment
- Emit per-trade log if fallback fires
- Update audit: `delisted_cost_basis_fallback_eliminated = True`

#### 6.3 Fix A2

- Construct `historical_universe_membership_*.csv` to include delisted-before-snapshot members
- Test: synthetic 10-ticker universe with 2 delisted → coverage = 100% pre-delisting, > 95% post
- Update audit: `survivorship_coverage_audited = True` with `survivorship_coverage_pct = ___`

#### 6.4 Verification

After both fix PRs merged:
- `research/broker_accounting_audit.json` shows both `passed: true`
- `tools/auto_policy_challenger.py` re-run shows new baseline numbers (likely CAGR reduces 2-5pp from survivorship adjustment)

#### 6.5 Why this MUST happen before Phase C8

`auto_policy_challenger.py` includes A1/A2 as hard gates. Without them passing,
Phase C8 promotion logic will refuse to merge anything → blocking all subsequent
production weight changes.

---

## 7. Dependency Graph (DAG)

```
┌─────────────────────────────────────────────────────────────────────┐
│                                                                       │
│  C0.1 KILL SWITCH ──► (merge to master)                              │
│       │                                                               │
│       ├──► D1 13F events ──────────┐                                 │
│       ├──► D5 Form4 P-only ────────┤                                 │
│       └──► D7 13D activist ────────┴──► D2 labels ──► D3 scores ──┐ │
│                                                                     │ │
│                                                                     ▼ │
│                                                              D4 live ─┤
│                                                              D6 follow│
│                                                                     │ │
│                                                                     ▼ │
│                                                              C4 challenger
│                                                                     │ │
│                                                                     ▼ │
│                                                              C6 Top30 │
│                                                              C7 after-svc
│                                                                       │
│  C5 ETF PIT ──────────────────► D2 (4th stream extension)            │
│                                                                       │
│  Broker A1/A2 fix (INDEPENDENT) ──► [unblocks] ──► C8 + C9 promotion │
│                                                                       │
└─────────────────────────────────────────────────────────────────────┘
```

### 7.1 Concurrency policy

- D1, D5, D7 모두 **C0.1 merge 후 동시 시작 가능** (다른 파일들)
- D2 + D3 같은 브랜치 (sequential), 위 3개 다 머지 후 시작
- D4 + D6 D2/D3 머지 후 동시 시작 가능
- C5 (ETF PIT) 는 fully independent — foundation merge 후 언제든 시작
- A1/A2 broker fix 는 day 1 부터 시작 가능 (fully independent)
- C8 + C9 는 모든 위 PR 머지 + 6mo SHIP 후만

---

## 8. Verification Matrix

| Phase | Smoke Test | Local Run | Cloud Rebuild | Cost Sens | A1/A2 Gate |
|---|:-:|:-:|:-:|:-:|:-:|
| C0.1 Kill Switch | 4 new | ✓ verdict-only | ✗ (no behavior change) | ✗ | ✗ |
| D1 13F events | 3 new | ✗ | ✗ | ✗ | ✗ |
| D5 Form4 P-only | 3 new | ✗ | ✗ | ✗ | ✗ |
| D7 13D activist | 2 new | ✗ | ✗ | ✗ | ✗ |
| D2 labels | 3 new | ✗ | ✗ | ✗ | ✗ |
| D3 scoring | 4 new | ✓ | ✗ | ✗ | ✗ |
| D4 live PDA | 4 new | ✓ verdict-only (off) | ✓ off vs on | ✗ | ✗ |
| D6 follow/fade | 3 new | ✗ | ✗ | ✗ | ✗ |
| C4 challenger | 5 new | ✓ | ✓ (8 scenarios A-H) | ✓ | ✗ |
| C5 ETF PIT | 3 new | ✗ | ✗ | ✗ | ✗ |
| C6 Top30 standalone | 3 new | ✓ | ✗ | ✗ | ✗ |
| C7 after-service | 4 new | ✗ | ✗ | ✗ | ✗ |
| Broker A1/A2 fix | 3 new | ✗ | ✓ (baseline revision) | ✗ | ✓ |
| C8 promotion | 5 new | ✓ | ✓ | ✓ | **REQUIRED** |
| C9 regime mult | 2 new | ✓ | ✓ | ✓ | **REQUIRED** |

---

## 9. Safety Net (운영 규칙)

### 9.1 Kill switch invariants

- 모든 PR diff에서 다음 라인이 변경되지 않아야 함 (regression test):
  - `r1000_config.py`: `sec_evidence_apply_to_live_score: bool = False`
  - `r1000_config.py`: `pda_apply_to_live_score: bool = False`
- 변경하려면 별도 `chore/flip-kill-switch-YYYY-MM-DD` 브랜치 + 사람 승인 PR
- 그 PR 의 verification: 6mo SHIP verdict 첨부, A1/A2 통과 첨부, Phase C4 SHIP 결과 첨부

### 9.2 Auto-merge blocking

다음 단어 중 하나라도 PR description에 있으면 자동 머지 차단:
- `[skip-auto-promote]`
- `BLOCKING`
- `RFC`
- `DO NOT MERGE`

### 9.3 Weight delta cap

분기당 가중치 변동 ≤ 30% (예: `w_pda_13f` 0.06 → 0.075 가능, 0.06 → 0.10 차단).

### 9.4 PIT discipline 자동 검증

NEW: `tools/run_pit_audit_for_pda.py`
- 모든 D1/D5/D7 events에서 `available_from_ts >= accepted_at_ts` 검증
- D2 labels에서 `entry_close_ts > available_from_ts` 검증
- D4 live scoring에서 `as_of_date` 이전 데이터만 사용 검증
- CI에서 매 PR마다 실행, 위반 1개라도 시 fail

---

## 10. Timeline (15-22일)

### Week 1 (Day 1-5): Foundation + Independent Tracks

| Day | Action | Branch |
|---|---|---|
| 1 | Phase C0.1 kill switch PR | `codex/plan-c-foundation` |
| 1 | Phase A1/A2 broker fix PR (parallel) | `codex/plan-c-broker-a1-a2-fix` |
| 2 | C0.1 merge → rebase D1/D5/D7 branches off master | — |
| 2-3 | D1 13F event builder | `codex/plan-c-d1-13f-events` |
| 2-3 | D5 Form4 P-only | `codex/plan-c-d5-form4-pcode` |
| 2-4 | D7 13D activist | `codex/plan-c-d7-13d-activist` |
| 2-5 | C5 ETF PIT start | `codex/plan-c-c5-etf-pit` |

### Week 2 (Day 6-12): Labeling + Learning

| Day | Action | Branch |
|---|---|---|
| 6 | D1+D5+D7 merge to master | — |
| 7-8 | D2 labeler | `codex/plan-c-d2-d3-labels-scores` |
| 9-10 | D3 multi-bucket scoring | (same branch) |
| 11-12 | D6 follow vs fade validation | `codex/plan-c-d6-follow-fade` |
| 6-12 | Phase C1 manual SEC trigger (when foundation in place) | GitHub UI |

### Week 3 (Day 13-18): Live + Standalone

| Day | Action | Branch |
|---|---|---|
| 13 | D2+D3 merge | — |
| 14-16 | D4 live PDA scoring | `codex/plan-c-d4-live-scoring` |
| 14-16 | C6 Top30 standalone (parallel) | `codex/plan-c-c6-top30-watchlist` |
| 14-17 | C7 after-service infra (parallel) | `codex/plan-c-c7-after-service` |
| 17-18 | C4 broker challenger (8 scenarios) | `codex/plan-c-c4-broker-challenger` |

### Week 4+ (Day 19+): Validation & Promotion (months, not days)

| Activity | Cadence |
|---|---|
| Monthly cloud rebuild + 8-scenario challenger | monthly |
| Wait for 6 consecutive SHIP verdicts | 6 months |
| Human approval recording | once |
| Phase C8 + C9 promotion enable | 7th month |

---

## 11. Codex Agent Operating Rules

### 11.1 Before each PR

1. Read `/root/.claude/plans/elegant-sniffing-dragon.md` Part F (v3.5 spec)
2. Read this file (`CODEX_HANDOFF_PLAN_C_V3_5_20260520.md`) §5 for the specific phase
3. Confirm dependency branches are merged to master (run `git log --oneline origin/master ^origin/codex/plan-c-foundation | head`)
4. Pull latest master, rebase your feature branch
5. Verify base file state matches §3 (verified code state) — if drift, halt and ask

### 11.2 PR description requirements

```markdown
## Plan C v3.5 — Phase <ID>: <Title>

### Plan reference
- /root/.claude/plans/elegant-sniffing-dragon.md Part F (§F.<n>)
- CODEX_HANDOFF_PLAN_C_V3_5_20260520.md §<n>
- Depends on: <list of merged branches>

### Why
<3-5 lines from the spec>

### What
<bullet list of file changes>

### Production impact
<ZERO / shadow-only / etc.>

### Verification
- [ ] tests/smoke_test.py passes (X new tests added)
- [ ] Local run not affected (kill switch off)
- [ ] PIT discipline audit passes
- [ ] No hardcoded tickers
- [ ] No `report_period` used as availability

### Safety
- [ ] Kill switch line in r1000_config.py UNCHANGED
- [ ] No auto-merge override flags
- [ ] Weight delta ≤ 30% (if applicable)

https://claude.ai/code/session_01PLAN_C_V3_5_CODEX
```

### 11.3 Commit message convention

```
<type>(plan-c-<phase>): <summary>

<body>

Plan ref: CODEX_HANDOFF_PLAN_C_V3_5_20260520.md §<n>
```

Types: `feat`, `fix`, `test`, `docs`, `refactor`, `chore`

### 11.4 Halt-and-ask triggers

Codex MUST stop and request human review if any of these happen:

- Discovery that §3 verified code state has drifted (file structure changed)
- A1/A2 broker accounting audit unexpectedly already passing
- SEC data trigger fires before kill switch merges
- A merge conflict cannot be resolved with rebase
- A test fails on master after rebase (master broke)
- Weight delta would exceed 30% in any single PR
- Auto-promote PR fails CI 3+ times in a row

### 11.5 Forbidden actions

- ❌ `git push --force` on shared branches (master, codex/plan-c-foundation)
- ❌ `--no-verify` on commits
- ❌ Modifying `tests/smoke_test.py` to make a failing test pass without fixing the underlying code
- ❌ Removing kill switch lines from r1000_config.py
- ❌ Direct edit of `data_pit/sec/*.parquet` (must be regenerated via tools)
- ❌ Adding new top-level dependencies without updating requirements.txt + Colab notebook

---

## 12. Integration & Merge Sequence (Final)

```
Day 0:   create codex/plan-c-foundation from master
Day 1:   merge codex/plan-c-foundation (C0.1) to master
Day 1:   create codex/plan-c-broker-a1-a2-fix from master (parallel)
Day 2:   create D1, D5, D7, C5 branches from master
Day 6:   merge D1, D5, D7 (sequential or batch)
Day 7:   create D2-D3 branch from master
Day 13:  merge D2-D3
Day 14:  create D4, D6, C6, C7 branches from master
Day 17:  merge D4, D6 (D4 first)
Day 18:  create C4 challenger branch from master
Day 19:  merge C4 + C6 + C7
Day 20:  cloud rebuild on all merged branches
Day 21-N: monthly SHIP verdict tracking, 6mo wait for C8/C9
Day 180: enable C8/C9 promotion if A1/A2 pass + 6mo SHIP
```

---

## 13. Reference Snippets

### 13.1 `numeric_series_or_default` (already exists)

Used throughout this plan. Located at `r1000_pipeline.py:numeric_series_or_default` — returns `pd.Series` with `0.0` fallback if column missing. **DO NOT redefine in new code**.

### 13.2 Existing PDA infrastructure to reuse

| Function | Location | Use in |
|---|---|---|
| `manager_alpha()` | `tools/run_sec_evidence_signal_audit.py:207-276` | Phase D3 (extend, don't replace) |
| `forward_return()` | `r1000_rule_backtester.py:80-88` | Phase D2 labeler |
| `add_13f_position_deltas()` | `tools/run_sec_institutional_signals.py:70` | Phase D1 |
| `prepare_13f_holdings()` | `tools/run_sec_institutional_signals.py` | Phase D1 (PIT timestamps) |
| `auto_policy_challenger.py` | `tools/auto_policy_challenger.py` | Phase C4 + C8 |

### 13.3 Configuration constants to update

| Constant | File | Phase | Default |
|---|---|---|---|
| `sec_evidence_apply_to_live_score` | r1000_config.py | C0.1 | False |
| `pda_apply_to_live_score` | r1000_config.py | C0.1 | False |
| `sec_evidence_bonus_cap` | r1000_config.py | C0.1 | 0.20 |
| `pda_bonus_cap` | r1000_config.py | C0.1 | 0.15 |
| `w_pda_13f` | r1000_config.py | C0.1 | 0.0 (learned later) |
| `w_pda_form4` | r1000_config.py | C0.1 | 0.0 |
| `w_pda_13d` | r1000_config.py | C0.1 | 0.0 |
| `w_pda_etf` | r1000_config.py | C0.1 | 0.0 |
| `sec_evidence_min_form4_signal_tickers` | r1000_config.py | C0.1 | 300 |
| `sec_evidence_min_13f_signal_tickers` | r1000_config.py | C0.1 | 100 |
| `sec_evidence_max_stale_days` | r1000_config.py | C0.1 | 240 |

---

## 14. Open Questions for Human

Before Codex starts, please confirm:

1. **Branch base for foundation**: `master` or `claude/short-rs-plus-sec-evidence-merged`?
   - master = clean, but misses PR #16 SEC overlay code
   - claude/short-rs-plus-sec-evidence-merged = has SEC overlay + plan docs
   - **Recommendation**: master (kill switch fix applies to actual production code)

2. **Codex 작업 가능 시간**: 동시 N개 PR 가능? (concurrent branches)
   - Plan assumes 4-5 concurrent branches at peak (D1/D5/D7/A1A2/C5)

3. **6개월 SHIP wait**: 단축 가능?
   - 3개월로 단축 시 risk
   - 6개월 = ChatGPT 권장

4. **Telegram bot 통합**: existing bot 재사용 vs new?

5. **GitHub Actions cost**: 일별 + 분기 cron 추가로 ~50% 증가 예상. 한도 있나?

---

## 15. Single Highest-Leverage First Action

```
1. Codex: create branch codex/plan-c-foundation from master
2. Codex: implement Phase C0.1 (§5.1) — kill switch
3. Codex: open PR with template (§11.2)
4. Human: review, approve, merge
5. Codex: rebase D1, D5, D7, C5 branches off updated master
6. Codex: start D1 + D5 + D7 in parallel (3 PRs)
7. Independent: human triggers Phase C1 SEC workflows (kill switch protects)
8. Independent: codex/plan-c-broker-a1-a2-fix starts day 1
```

이 7개 액션이 끝나면 PDA framework의 **데이터 + 안전 인프라**가 동시에 완성된다. 그 후 D2-D6 학습 phase로 진행.

---

# Part II — Final Integrated Engine Addendum (v3.6, 2026-05-24)

This addendum extends the v3.5 handoff after the user's 2026-05-23 directive to add
**CAGR-Preserving Crisis Governor** + **Hold-vs-Replace Discipline** + **Integrated
Challenger** on top of the existing PDA framework. The original v3.5 phases
(C0.1/D1/D5/D7/D2/D3/D4/D6/C4/C5/C6/C7/C8/C9) remain valid; this section adds
Phase E (Crisis Governor), Phase F (Hold-vs-Replace), Phase G (Integrated
Challenger) and revises promotion targets to the **official broker-ledger
baseline** rather than research backtest numbers.

## 16. Final Integrated Engine Vision (Verified Baselines)

### 16.1 Official broker-ledger baselines (use these for promotion, NOT research)

| Portfolio | CAGR | MDD | Sharpe | Source |
|---|---:|---:|---:|---|
| main | **20.35%** | **-33.45%** | 0.991 | broker_ledger_next_close (master) |
| concentrated | **36.41%** | **-38.45%** | 1.186 | broker_ledger_next_close (master) |

Drawdown anatomy:
- **main**: peak 2021-11-19 → trough 2022-10-14 (slow bear, rate-hike regime)
- **concentrated**: peak 2020-02-19 → trough 2020-03-16 (shock crash, COVID)

→ These two crisis archetypes drive Phase E design.

### 16.2 Research backtest numbers are NOT promotion metrics

Do NOT optimize against `outputs/backtest_metrics.json` CAGR 29.19% or
`outputs/concentrated_backtest_metrics.json`. These are PROXY metrics with
known survivorship + delisted_cost_basis_fallback gaps (A1/A2 audits failing).
Use only `broker_ledger_next_close` output.

### 16.3 7-Layer Combined Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  Layer 1: Future Winner Core (existing, primary selector)            │
│           portfolio_future_winner_engine_score                       │
│                                                                       │
│  Layer 2: Smart Money Confirmation (Phase D output, NOT primary)     │
│           smart_money_confirmation_score (formula §17.2)             │
│                                                                       │
│  Layer 3: Post-Disclosure Alpha (Phase D2/D3 output)                 │
│           post_disclosure_alpha_score                                │
│                                                                       │
│  Layer 4: ETF / Theme Confirmation (Phase C5 PIT holdings)           │
│           etf_theme_confirmation_score                               │
│                                                                       │
│  Layer 5: Hold-vs-Replace Discipline (Phase F, NEW)                  │
│           replacement_quality_score                                   │
│                                                                       │
│  Layer 6: Crisis Governor (Phase E, NEW)                             │
│           crisis_score + exposure_ladder + reentry_score             │
│                                                                       │
│  Layer 7: Broker-Ledger Promotion Gate (existing)                    │
│           broker_ledger_next_close + A1/A2 + stress window           │
└──────────────────────────────────────────────────────────────────────┘
```

### 16.4 Final Selection Score Formulas

**Main** (CAGR 25%+ / MDD -25%- target):
```python
main_selection_score = (
    0.42 * future_winner_score
  + 0.20 * market_confirmation_score
  + 0.12 * industry_theme_leadership_score
  + 0.10 * quality_growth_score
  + 0.08 * smart_money_confirmation_score
  + 0.05 * post_disclosure_alpha_score
  + 0.03 * entry_quality_score
)
```

**Concentrated** (CAGR 40%+ / MDD -28%- target, N=2/3/5 only, **N7 forbidden**):
```python
concentrated_selection_score = (
    0.32 * future_winner_score
  + 0.22 * market_confirmation_score
  + 0.15 * smart_money_confirmation_score
  + 0.10 * post_disclosure_alpha_score
  + 0.10 * industry_theme_leadership_score
  + 0.06 * entry_quality_score
  + 0.05 * quality_growth_score
)
```

**Smart Money Confirmation** (consolidates 4-stream PDA into single confirmation):
```python
smart_money_confirmation_score = (
    0.30 * form4_cluster_buy_score
  + 0.25 * post_13f_alpha_score
  + 0.15 * manager_quality_score
  + 0.10 * multi_manager_convergence_score
  + 0.10 * etf_theme_confirmation_score
  + 0.10 * industry_smart_money_flow_score
  - 0.15 * crowding_or_stale_penalty
)
```

**Tenbagger Discovery** (watchlist + replacement pool ONLY, not production buys):
```python
tenbagger_discovery_score = (
    0.25 * future_winner_score
  + 0.20 * smallcap_high_growth_score
  + 0.15 * post_disclosure_alpha_score
  + 0.15 * theme_structural_growth_score
  + 0.10 * insider_conviction_score
  + 0.10 * volume_breakout_score
  + 0.05 * low_float_supply_score
)
```

Output: `outputs/tenbagger_watchlist/latest.csv` — daily refresh, manual-review only.

---

## 17. Phase E — CAGR-Preserving Crisis Governor (NEW)

**Branch**: `codex/plan-c-e-crisis-governor` (base: master post foundation merge)
**Effort**: 5-7 days
**Dependency**: Phase C0.1 (kill switch). Can run in parallel with D-track.

### 17.1 Core principle (memorize)

| WRONG defense (CAGR-killer) | RIGHT defense (CAGR-preserving) |
|---|---|
| Permanent cash 15-25% | Cash 0-5% in normal markets |
| Stop-loss everywhere | Trim only broken positions |
| Slow rebalance to "let dust settle" | Replace broken with stronger leader |
| Sell everything in panic | Exposure ladder + re-entry ladder |
| Re-enter when "things look good" | Re-enter when reentry_score crosses thresholds |

### 17.2 Phase E1 — Drawdown segment audit

NEW: `tools/run_drawdown_segment_report.py`

Outputs:
- `outputs/drawdown_segments/main.csv`
- `outputs/drawdown_segments/concentrated.csv`
- `outputs/drawdown_segments/report.md`

Columns:
```
peak_date, trough_date,
first_below_10d, first_below_20d, first_below_30d,
days_below_30pct, max_drawdown_pct,
cash_weight_at_first_below_10, cash_weight_at_first_below_20,
cash_weight_at_trough, cash_weight_at_recovery,
position_count_at_peak, position_count_at_trough,
top_3_holdings_at_peak, top_3_holdings_at_trough,
held_winner_count, held_broken_count,
new_buys_during_dd, sells_during_dd
```

Purpose: empirically diagnose how main 2021-11→2022-10 and concentrated
2020-02→2020-03 went wrong. No optimization yet — just truth-finding.

### 17.3 Phase E2 — Crisis signal builder

NEW: `tools/run_crisis_signal_builder.py`

Uses only data available at T close (no look-ahead):
```python
crisis_features = {
    # Market trend
    "spy_below_ma200": bool,
    "qqq_below_ma200": bool,
    "spy_5d_dd": float,
    "spy_20d_dd": float,
    "qqq_5d_dd": float,
    "qqq_20d_dd": float,
    # Volatility
    "vix_level": float,
    "vix_zscore_60d": float,
    "vix_spike_3d": float,
    # Credit
    "hy_spread_bps": float,         # HY OAS
    "ig_spread_bps": float,         # IG OAS
    "hy_spread_zscore_60d": float,
    # Rates
    "ten_year_yield": float,
    "ten_year_5d_change_bps": float,
    "yield_curve_inversion": bool,  # 2s10s
    # Breadth
    "pct_stocks_above_ma200": float,
    "pct_stocks_above_ma50": float,
    "advdec_line_slope_20d": float,
    # Liquidity
    "spy_dollar_volume_zscore": float,
    "qqq_dollar_volume_zscore": float,
    # Portfolio
    "current_drawdown_pct": float,
    "weighted_holdings_drawdown": float,
}
```

Output: `outputs/crisis_signals/daily_features.parquet` (one row per trading day)

### 17.4 Phase E3 — Crisis type classifier

NEW: `tools/run_crisis_type_classifier.py`

Rule-based + optional ML refinement:

| Crisis type | Detection rule |
|---|---|
| `shock_crash` | spy_5d_dd > 8% AND vix_zscore > 2.5 |
| `slow_bear` | spy_below_ma200 AND qqq_below_ma200 AND days_below_ma200 > 30 AND 10y_yield rising |
| `credit_crisis` | hy_spread_zscore > 2.0 AND ig_spread_zscore > 1.5 |
| `normal_pullback` | spy_5d_dd in [3%, 8%] AND vix_zscore in [0.5, 2.0] |
| `recovery` | vix_zscore < 0.5 AND spy_above_ma50 AND breadth_thrust |
| `normal` | none of above |

Output: daily classification → `outputs/crisis_signals/daily_classification.csv`

### 17.5 Phase E4 — Composite crisis_score

```python
crisis_score = (
    0.25 * market_trend_breakdown      # spy/qqq below MA200 + 20d_dd
  + 0.20 * credit_stress_score         # HY/IG spread z-scores
  + 0.15 * volatility_spike_score      # VIX level + z-score
  + 0.15 * breadth_breakdown_score     # pct above MA200
  + 0.10 * liquidity_drain_score       # dollar volume anomaly
  + 0.10 * rate_shock_score            # 10y yield 5d change
  + 0.05 * portfolio_damage_score      # current_dd + weighted_holdings_dd
)  # all components clipped to [0, 1]
```

### 17.6 Phase E5 — Exposure ladder

NEW config (`r1000_config.py`):
```python
# Plan C v3.6 Phase E — Crisis governor (default OFF until validated)
crisis_governor_apply_to_live: bool = False
crisis_score_thresholds: list[float] = [0.30, 0.50, 0.70]
crisis_cash_ladder: dict = {
    "normal":   (0.00, 0.05),    # crisis < 0.30
    "caution":  (0.05, 0.10),    # 0.30-0.50
    "defense":  (0.10, 0.25),    # 0.50-0.70
    "crisis":   (0.25, 0.50),    # >= 0.70
}
crisis_new_buy_throttle_at: float = 0.30   # block new buys above this score
crisis_concentrated_exposure_floor: float = 0.30  # min equity in crisis state
```

Behavior per zone:
| Zone | Cash | New buys | Existing holdings | Trim policy |
|---|---|---|---|---|
| normal | 0-5% | normal | hold all | none |
| caution | 5-10% | throttle 50% | hold winners | trim breaks if replacement avail |
| defense | 10-25% | block | hold winners | trim broken high-beta, prefer replacement |
| crisis | 25-50% | block | hold winners only | reduce concentrated to 30-50% exposure |

### 17.7 Phase E6 — Re-entry ladder

```python
reentry_score = (
    0.30 * vix_normalization           # vix_zscore < 0.5
  + 0.25 * qqq_ma_reclaim              # QQQ > MA20 OR MA50 reclaim
  + 0.20 * breadth_thrust              # advdec_line_slope_20d > 0.3
  + 0.15 * credit_spread_stabilization # HY zscore < 0.8
  + 0.10 * leadership_recovery         # top-5 holdings outperform SPY 10d
)
```

Re-entry rule:
| reentry_score | Action |
|---|---|
| < 0.40 | hold defense state |
| 0.40 - 0.60 | add 25% risk (reduce cash by 25% of ladder) |
| 0.60 - 0.75 | add 50-70% risk |
| > 0.75 | full normal risk restore |

Crisis-type-specific re-entry pacing:
| Crisis type | Re-entry speed |
|---|---|
| shock_crash | fast (2020 COVID needed 4-week re-entry) |
| slow_bear | gradual (2022 needed quarter-by-quarter confirmation) |
| credit_crisis | wait for credit stabilization before any add |

### 17.8 Phase E7 — Governor replay tool

NEW: `tools/run_cagr_preserving_crisis_governor_replay.py`

Replays main + concentrated portfolios with governor enabled across the full
broker-ledger history. Outputs:
- `outputs/crisis_governor_replay/main_with_governor.csv` (daily ledger)
- `outputs/crisis_governor_replay/concentrated_with_governor.csv`
- `outputs/crisis_governor_replay/stress_window_metrics.csv`
- `outputs/crisis_governor_replay/false_alarm_log.csv`

Stress windows (mandatory):
- 2020-02-01 to 2020-05-31 (COVID shock)
- 2021-11-01 to 2022-12-31 (rate-hike slow bear)
- 2024-01-01 to 2024-12-31 (latest year, sanity)
- 2025-01-01 to latest (most recent)

For each window:
- CAGR with vs without governor
- MDD with vs without governor
- Rebound capture (days to recover 80% of peak)
- Re-entry lag (days between reentry_score > 0.40 and actual exposure increase)
- Cash trap days (consecutive days at >25% cash when SPY was actually rising)
- False alarm count (governor triggered defense state but no drawdown materialized)
- Turnover + fees increase

### 17.9 Phase E8 — Tests

```python
@_test
def phase_e_crisis_governor_default_off():
    """Phase E — governor must default OFF, production behavior unchanged."""
    cfg = EngineConfig()
    assert cfg.crisis_governor_apply_to_live is False

@_test
def phase_e_normal_zone_keeps_low_cash():
    """Phase E — when crisis_score < 0.30, cash target stays 0-5%."""

@_test
def phase_e_crisis_zone_blocks_new_buys():
    """Phase E — crisis state must block new_buy decisions."""

@_test
def phase_e_reentry_ladder_monotonic():
    """Phase E — re-entry exposure adds never reverse without crisis score deterioration."""

@_test
def phase_e_no_future_data_in_signals():
    """Phase E — crisis features at time T use only data available at T close."""
```

---

## 18. Phase F — Hold-vs-Replace Discipline (NEW)

**Branch**: `codex/plan-c-f-hold-vs-replace`
**Effort**: 3-4 days
**Dependency**: Phase D4 (live PDA scoring) for replacement candidate pool

### 18.1 Decision matrix

| Position state | Action |
|---|---|
| **Winner intact** (above entry, RS > 60, no break) | HOLD (do not sell only because of market volatility) |
| **Weakening** (between -5% and -15%) | TRIM 25-50% only if replacement clearly better |
| **Broken** (below -15% OR MA200 violation OR RS < 30) | Replace if candidate available, else cash (crisis) |
| **Winner overextended** (above target gain or P/E spike) | Hold but no add — let it run |

### 18.2 Replacement candidate thresholds

```python
# z-score relative to held position's selection_score
NORMAL_REPLACEMENT_THRESHOLD = 0.75       # candidate must beat held by 0.75 sigma
WEAKENING_REPLACEMENT_THRESHOLD = 0.35    # easier swap when held is weakening
CRISIS_REPLACEMENT_RULE = "quality_defensive_only"  # only swap to leaders/defensive
```

### 18.3 NEW tool: `tools/run_hold_vs_replace_evaluator.py`

Inputs:
- Current portfolio (`portfolio_latest.csv`)
- Tenbagger watchlist (`outputs/tenbagger_watchlist/latest.csv`)
- Smart money top30 (`outputs/smart_money/top30_latest.csv`)
- Crisis state (Phase E output)

Output: `outputs/hold_vs_replace/decisions.csv`
```
ticker, current_state, recommendation,
held_score, candidate_ticker, candidate_score, score_delta_sigma,
replace_reason, risk_off_safety_check
```

### 18.4 Replacement safety guards

- Never replace if candidate is in same broken sector AND same broken industry
- Never reduce concentrated to below `crisis_concentrated_exposure_floor` (0.30)
- Crisis-mode replacement must be from `quality_growth_score > 0.7` pool only
- Replacement requires `available_from_ts` PIT discipline (no replacing on future signal)

---

## 19. Phase G — Integrated Alpha+Crisis Challenger (NEW)

**Branch**: `codex/plan-c-g-integrated-challenger`
**Effort**: 4-5 days
**Dependency**: All Phase D + Phase E + Phase F merged + Phase C4 broker-ledger
                infrastructure available

### 19.1 NEW tool: `tools/run_integrated_alpha_crisis_challenger.py`

Multi-dimensional grid search across:

| Dimension | Values |
|---|---|
| main target_n | 12, 15, 18 |
| concentrated target_n | 2, 3, 5 (NEVER 7) |
| evidence weight (main) | 0.05, 0.08, 0.10 |
| evidence weight (concentrated) | 0.10, 0.15, 0.20 |
| crisis governor | OFF, ON-conservative, ON-aggressive |
| hold-vs-replace | OFF, ON-normal, ON-strict |
| smart_money_confirmation contribution | OFF, 0.05, 0.08 |
| post_disclosure_alpha contribution | OFF, 0.03, 0.05 |

Each combination → full broker-ledger replay with stress window metrics.

### 19.2 Promotion gates (broker-ledger only)

**Main**:
- ΔCAGR ≥ -0.5pp (preferably positive)
- ΔMDD ≥ +5pp (current -33.45% → -28% or better)
- 2022 stress MDD improves materially (vs -33% benchmark)
- turnover increase ≤ +20%
- fees increase ≤ +20%
- A1/A2 broker_accounting_audit both `passed=True`

**Concentrated**:
- ΔCAGR ≥ -3pp (preferably positive)
- ΔMDD ≥ +10pp (current -38.45% → -28% or better)
- 2020 stress MDD improves toward -25% to -28%
- N=2/3/5 only (N=7 disqualified — N7 is diversified sleeve, not concentrated)
- rebound capture within 2 weeks of reentry_score > 0.6
- no permanent cash trap (>30% cash for >60 days during rising market)

### 19.3 Output

`outputs/integrated_challenger/grid_results.csv` — full matrix
`outputs/integrated_challenger/verdict.json` — best combo + SHIP/PARTIAL/REJECT
`outputs/integrated_challenger/stress_window_matrix.csv` — per-window per-combo

---

## 20. Revised Targets (FINAL)

| Portfolio | Metric | Current (official) | Phase 1 target | Final target |
|---|---|---:|---:|---:|
| main | CAGR | 20.35% | ≥ 20% | 25-30% |
| main | MDD | -33.45% | ≤ -25% | ≤ -15% |
| main | normal cash | ~18% | ≤ 8% | ≤ 5% |
| concentrated | CAGR | 36.41% | ≥ 33% | 40-50% |
| concentrated | MDD | -38.45% | ≤ -28% | ≤ -18% |
| concentrated | N | varies | 3 or 5 (N7 forbidden) | 3 or 5 |
| concentrated | 2020 stress MDD | -38% | -25% to -28% | -20% |

Phase 1 = after Phase E + F + G merged + 3mo SHIP verdicts.
Final = after 6mo SHIP verdicts + A1/A2 passing + bootstrap CI lower bound.

---

## 21. Revised Timeline (v3.6)

```
Week 1: Foundation
  Day 1:   C0.1 kill switch
  Day 1-5: A1/A2 broker fix (parallel)
  Day 2-3: D1/D5/D7 (parallel) + E1 drawdown segment audit
  Day 3-5: E2 crisis signal builder (parallel)

Week 2: Crisis + Labels
  Day 6:   Merge D1+D5+D7
  Day 7-8: D2 labeler
  Day 8-10: E3 crisis classifier + E4 composite score (parallel)
  Day 9-10: D3 multi-bucket scoring

Week 3: Live Integration
  Day 11-12: E5 exposure ladder + E6 reentry ladder
  Day 13-14: F hold-vs-replace (parallel to D4 live scoring)
  Day 13-14: D4 live PDA scoring
  Day 15:    E7 governor replay tool

Week 4: Integrated Challenger
  Day 16-18: G integrated challenger grid
  Day 19-20: Stress window validation (2020 + 2022 + 2024 + 2025)
  Day 21:    First SHIP/PARTIAL/REJECT verdict

Months 2-7: 6mo consecutive SHIP wait
  Quarterly: D6 follow-vs-fade re-validation
  Quarterly: Phase G grid re-search
  Monthly:   Stress window metrics tracking

Month 7+: Phase C8/C9 promotion unlock (A1/A2 + 6mo SHIP)
```

Total active dev: **~21 days** (3 weeks). SHIP wait: 6 months.

---

## 22. Updated Branch Topology (v3.6)

```
master
 ├─ codex/plan-c-foundation (C0.1)             ← merge first
 ├─ codex/plan-c-broker-a1-a2-fix              ← independent, day 1
 │
 ├─ codex/plan-c-d1-13f-events                 ← parallel
 ├─ codex/plan-c-d5-form4-pcode                ← parallel
 ├─ codex/plan-c-d7-13d-activist               ← parallel
 ├─ codex/plan-c-e1-dd-segment-audit           ← parallel (E1, truth-finding)
 ├─ codex/plan-c-e2-crisis-signals             ← parallel (E2)
 │
 ├─ codex/plan-c-d2-d3-labels-scores           ← after D1+D5+D7
 ├─ codex/plan-c-e3-e4-crisis-classify         ← after E2
 │
 ├─ codex/plan-c-e5-e6-ladders                 ← after E3+E4
 ├─ codex/plan-c-d4-live-scoring               ← after D3
 ├─ codex/plan-c-d6-follow-fade                ← after D3, parallel D4
 ├─ codex/plan-c-f-hold-vs-replace             ← after D4
 │
 ├─ codex/plan-c-e7-governor-replay            ← after E5+E6
 │
 ├─ codex/plan-c-c4-broker-challenger          ← after D4+D6
 ├─ codex/plan-c-g-integrated-challenger       ← after E7+F+C4
 │
 ├─ codex/plan-c-c5-etf-pit                    ← independent
 ├─ codex/plan-c-c6-top30-watchlist            ← after D4
 ├─ codex/plan-c-c7-after-service              ← after D4
 │
 └─ codex/plan-c-c8-c9-promotion               ← BLOCKED until 6mo SHIP + A1/A2
```

---

## 23. CODEX MASTER PROMPT (v3.6 Final)

Copy-paste this entire block when launching Codex for the integrated engine work:

```
ROLE:
You are the Final Integrated Portfolio Engine Agent for r1000-quant-engine.

MISSION:
Build the best combined system aligned with these goals:
1. Improve official broker-ledger CAGR (main 20.35%, concentrated 36.41%).
2. Reduce MDD without sacrificing CAGR (main -33.45% → -25%, concentrated -38.45% → -28%).
3. Detect early future winners + tenbagger candidates via 13F/Form4/13D/ETF.
4. Smart Money is a CONFIRMATION layer, NOT the primary selector.
5. Defend 2020 shock crash and 2022 slow bear without permanent cash drag.
6. Validate everything with broker-ledger next-close replay.

VERIFIED OFFICIAL METRICS (use these, NOT research backtest):
- main: CAGR 20.35%, MDD -33.45%, Sharpe 0.991, peak 2021-11-19, trough 2022-10-14
- concentrated: CAGR 36.41%, MDD -38.45%, Sharpe 1.186, peak 2020-02-19, trough 2020-03-16

DO NOT:
- Optimize legacy/research metrics (e.g., 29.19% research CAGR).
- Use Smart Money as the primary selector — only confirmation.
- Use static ETF_LOOKTHROUGH as production PIT evidence.
- Use future returns as live signals.
- Raise permanent cash in normal markets (must stay 0-5%).
- Allow N=7 as concentrated champion (only N=2/3/5).
- Activate production defaults without human approval.

BEST SYSTEM COMBINATION:
1. Future Winner Core
2. Smart Money Confirmation
3. Post-Disclosure Alpha
4. ETF / Theme Confirmation
5. Hold-vs-Replace Discipline
6. Historical Crisis Governor
7. Broker-Ledger Promotion Gate

MAIN SCORE:
main_selection_score = (
  0.42 * future_winner_score
+ 0.20 * market_confirmation_score
+ 0.12 * industry_theme_leadership_score
+ 0.10 * quality_growth_score
+ 0.08 * smart_money_confirmation_score
+ 0.05 * post_disclosure_alpha_score
+ 0.03 * entry_quality_score
)

CONCENTRATED SCORE:
concentrated_selection_score = (
  0.32 * future_winner_score
+ 0.22 * market_confirmation_score
+ 0.15 * smart_money_confirmation_score
+ 0.10 * post_disclosure_alpha_score
+ 0.10 * industry_theme_leadership_score
+ 0.06 * entry_quality_score
+ 0.05 * quality_growth_score
)

SMART MONEY CONFIRMATION SCORE:
smart_money_confirmation_score = (
  0.30 * form4_cluster_buy_score
+ 0.25 * post_13f_alpha_score
+ 0.15 * manager_quality_score
+ 0.10 * multi_manager_convergence_score
+ 0.10 * etf_theme_confirmation_score
+ 0.10 * industry_smart_money_flow_score
- 0.15 * crowding_or_stale_penalty
)

TENBAGGER DISCOVERY (watchlist only, not production buys):
tenbagger_discovery_score = (
  0.25 * future_winner_score
+ 0.20 * smallcap_high_growth_score
+ 0.15 * post_disclosure_alpha_score
+ 0.15 * theme_structural_growth_score
+ 0.10 * insider_conviction_score
+ 0.10 * volume_breakout_score
+ 0.05 * low_float_supply_score
)

CRISIS SCORE:
crisis_score = (
  0.25 * market_trend_breakdown
+ 0.20 * credit_stress_score
+ 0.15 * volatility_spike_score
+ 0.15 * breadth_breakdown_score
+ 0.10 * liquidity_drain_score
+ 0.10 * rate_shock_score
+ 0.05 * portfolio_damage_score
)

EXPOSURE RULE:
- crisis_score < 0.30:  cash 0-5%, normal risk
- 0.30-0.50:            cash 5-10%, new-buy throttle, winner hold
- 0.50-0.70:            cash 10-25%, trim broken high-beta, replacement before cash
- >= 0.70:              cash 25-50%, concentrated 30-50%, re-entry ladder active

RE-ENTRY:
reentry_score = (
  0.30 * vix_normalization
+ 0.25 * qqq_ma20_or_ma50_reclaim
+ 0.20 * breadth_thrust
+ 0.15 * credit_spread_stabilization
+ 0.10 * leadership_recovery
)

REENTRY RULES:
- reentry_score > 0.40: add 25% risk
- reentry_score > 0.60: add 50-70% risk
- reentry_score > 0.75: normal risk

CRISIS TYPE DIFFERENTIATION:
- shock_crash (2020 archetype): fast defense + fast re-entry
- slow_bear (2022 archetype): gradual defense + slow re-entry
- credit_crisis: fast defense + wait for credit spread stabilization
- recovery: normal mode + leadership confirmation

PHASE 1 — Post-Disclosure Alpha Foundation:
Create:
- tools/run_13f_position_event_builder.py
- tools/run_post_disclosure_alpha_labeler.py
- tools/run_manager_disclosure_alpha_scoring.py
- tools/run_post_disclosure_signal_learning.py
- tools/run_post_disclosure_alpha_candidates.py

Use accepted_at / available_from only.
Entry = next close AFTER available_from.
Compute 5d/21d/42d/63d/126d returns and excess returns.

PHASE 2 — Integrated Score Columns (SHADOW):
Add columns but do NOT add to production score:
- smart_money_confirmation_score
- tenbagger_discovery_score
- post_disclosure_alpha_score
- manager_quality_score
- event_source_convergence_score

PHASE 3 — Crisis Governor:
Create:
- tools/run_drawdown_segment_report.py
- tools/run_crisis_signal_builder.py
- tools/run_crisis_type_classifier.py
- tools/run_cagr_preserving_crisis_governor_replay.py

Train/test on historical crisis windows:
- 2008, 2011, 2015/2016, 2018, 2020, 2022

PHASE 4 — Integrated Challenger:
Create:
- tools/run_integrated_alpha_crisis_challenger.py

Test grid:
- main target_n: 12, 15, 18
- concentrated target_n: 2, 3, 5 (NEVER 7)
- evidence weights: main 0.05/0.08/0.10, concentrated 0.10/0.15/0.20
- crisis governor on/off
- replacement swap on/off

PHASE 5 — Validation:
Use broker-ledger next-close ONLY. Include:
- integer shares
- fees
- cash ledger
- daily MDD
- cost sensitivity 25/50/75/100bps
- stress window metrics (2020, 2022, 2024, 2025)
- bootstrap CI
- A1/A2 broker accounting gates passed

PROMOTION GATE:
Main:
- CAGR improves OR decreases <= 0.5pp
- MDD improves >= 5pp
- 2022 stress MDD improves materially
- turnover increase <= 20%, fees increase <= 20%

Concentrated:
- CAGR loss <= 3pp, preferably improves
- MDD improves >= 10pp
- 2020 shock MDD improves toward -25% to -28%
- no permanent cash trap

DELIVERABLES:
First write:
research/final_integrated_engine_20260524/research.md

Then write:
research/final_integrated_engine_20260524/plan.md

Do NOT activate production defaults.
Do NOT auto-promote.
All work goes to feature branches per CODEX_HANDOFF §22 topology.
```

---

**END OF v3.6 ADDENDUM**

The original v3.5 spec above (§1-§15) remains the canonical implementation
reference for the PDA framework. This addendum (§16-§23) extends it with the
Crisis Governor + Hold-vs-Replace + Integrated Challenger layers per the
2026-05-23 user directive.

**END OF CODEX HANDOFF SPEC**

이 문서는 Codex 에이전트가 Plan C v3.5를 구현하기 위한 단일 source of truth. 본 문서와 `/root/.claude/plans/elegant-sniffing-dragon.md` Part F 사이에 모순이 생기면 **Part F가 우선** (이 문서는 implementation guide).
