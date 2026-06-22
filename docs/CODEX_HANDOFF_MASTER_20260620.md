> ⚠ **SUPERSEDED 2026-06-22** — 현행 진입점은 `docs/CODEX_HANDOFF_MASTER_20260622.md`. 이 문서는 §0 mission / §6 제약만 유효, 진행상태(§2/§3/§5)는 0622 문서 참조.

# Codex 마스터 핸드오프 — CAGR/MDD 강화 (7Y A/B + 10Y 트랙)

- 작성일: 2026-06-20 KST / 작성: Claude
- repo: `wscha231/r1000-quant-engine` / 작업·PR 브랜치: **`claude/pr146-review-analysis-6dkvd8`** (PR #147)
- 이 문서가 단일 진입점. 세부는 §1 read-order 문서들 참조.

---

## 0. Mission + Acceptance contract (user 지시 2026-06-20)

**아래는 "최소 달성치"다. 넘기는 게 끝이 아니라, 넘긴 뒤 최대한 더 높이는 게 목표.**

| | 최소 floor (절대) | stretch |
|---|---|---|
| **Main CAGR** | **≥ 35%** | 높을수록 |
| **Main MaxDD** | **≥ −25%** (더 얕게) | −25%보다 얕게 |
| **Conc CAGR** | **≥ 50%** | 높을수록 |
| **Conc MaxDD** | **≥ −25%** | −25%보다 얕게 |

- floor는 **절대 기준**이지 baseline 대비 델타가 아니다. **baseline보다 좋아져도 floor 미달이면 reject.**
- floor 다 넘긴 뒤 → CAGR 최대화 push (단 MDD floor + overfit 가드 OOS/IS는 깨지 말 것).
- broker-ledger next-close 기준만 official (CLAUDE.md 데이터 계약).

---

## 1. 먼저 읽어라 (read-order, 이미 커밋됨)

1. `docs/RUN214_BASELINE_CONFIRMED_20260620.md` — 정직한 7Y baseline (아래 §2).
2. `docs/CODEX_AB_EXECUTION_7Y_CAGR_MDD_20260620.md` — 7Y Family A/B 실행 설계 + 절대-floor 게이트(§0b) + env 메커니즘.
3. `docs/CODEX_INSTRUCTION_10Y_TRACK_20260620.md` — 10Y proxy 트랙 (P0→P6, 데이터 갭).
4. `CLAUDE.md` + `docs/ALPHAOPS_DATA_SYSTEM_CONTRACT.md` — 프로젝트 기본 + 데이터-first 계약.

---

## 2. 검증된 현재 상태 (run #214 `27873592126`, master `a3dbd01`, clean 7Y broker-ledger)

| | Main | Conc | floor |
|---|---:|---:|---|
| CAGR | **34.73%** | **45.47%** | 35% / 50% |
| MaxDD | **−26.05%** | −24.59% | −25% / −25% |
| Sharpe | 1.267 | 1.412 | — |
| IS CAGR | 20.37% | 18.85% | — |
| OOS/IS | 3.96x | **7.66x** | ≤3.0 |
| avg cash | 26.4% | **41.9%** | — |

- **Main: 두 floor 모두 미달** (CAGR −0.27pp, MDD −1.05pp). MaxDD = COVID 단일사건(2020-02-19→03-18, 28일).
- **Conc: CAGR floor −4.53pp 미달** (MDD는 통과). 평균현금 41.9% = 과방어, OOS/IS 7.66x = 과적합.
- 2 결함축: **(A) fast-crash 방어 실패**(Main MDD), **(B) bull cash drag + overfit**(Conc CAGR/OOS-IS).

---

## 3. 진행 중 / shipped (건드리지 말 것)

- **Family A env-override hook = shipped** (commit `70538b9`, `r1000_config.py` `_apply_fast_crash_env_overrides`, `FAST_CRASH_ENV_OVERRIDE_FIELDS` 23필드). `R1000_<FIELD_NAME_UPPER>`로 주입.
- **7Y Family A challenger 진행 중**: A1 run #216 `27887125658` (DD breaker), A2 run #217 `27887129839` (VIX floor). 둘 다 ref=이 브랜치, 빈 cache suffix(#214 캐시 재사용). **이 두 런은 Claude가 판정한다 — Codex는 건드리지 마라.**

---

## 4. A/B 주입 메커니즘 (필수 준수)

- `full_rebuild_manual.yml` 입력 `experiment_env_json` = JSON object. 키는 정규식 `^(PHASE_|R1000_|ALPHAOPS_)[A-Z0-9_]+$`만 허용(워크플로가 강제, 위반 시 exit 2).
- **env key = `R1000_` + EngineConfig 필드명 대문자.** 예: `drawdown_breaker_level_1_threshold` → `R1000_DRAWDOWN_BREAKER_LEVEL_1_THRESHOLD`. **약어 키는 hook이 무시하니 금지.**
- **반드시 ref = env-hook이 있는 브랜치**(`claude/pr146-review-analysis-6dkvd8`)에서 dispatch. master에서 돌리면 override가 조용히 무시됨.
- ceteris-paribus 위해 **빈 cache_key_suffix** 사용(#214 캐시 재사용). backtest_years=7, global_alpha_universe, skip_collector=true로 #214와 매칭.
- 새 cfg 필드를 A/B 하려면 먼저 `FAST_CRASH_ENV_OVERRIDE_FIELDS`(또는 동형 화이트리스트)에 추가(기본값 불변 = 측정 인프라, 정책 변경 아님).

---

## 5. 작업 — 두 병렬 트랙, 우선순위

### Track 1 — 7Y CAGR/MDD A/B (floor 달성이 1차 목표)
> Family A(#216/#217)는 Claude 진행 중. Codex는 **CAGR-lift 레버**와 **Family B**를 맡는다.

- **T1-a — Main CAGR-lift 레버 (신규, 중요).** fast-crash(A1/A2)는 MDD를 줄이지만 **Main CAGR을 35% 위로 올리지 못한다.** Main이 두 floor를 *동시에* 넘으려면 CAGR을 올리는 별도 레버가 필요. 후보: 과도한 평균현금(26.4%) 축소 / sleeve 노출 상향 / neutral-regime churn 감소. 먼저 attribution으로 Main CAGR 손실 원인을 특정한 뒤 단일 레버 A/B. 게이트: **Main CAGR ≥35% AND MaxDD ≥−25% 동시.**
- **T1-b — Family B env-hook 추가 (step-0).** `concentrated_regime_cash_vix_threshold`, `growth_reentry_strength`를 env-override 화이트리스트에 추가(기본값 불변). 이게 있어야 B1/B2 A/B 가능.
- **T1-c — C1 cash-trap attribution.** Conc 평균현금 41.9%를 crisis-cash vs bull-drag-cash로 분해해 어느 knob이 bull-drag를 만드는지 특정. (`is_attribution` / `cash_reentry_quality` 입력.)
- **T1-d — Family B A/B (B1/B2/B3).** C1 결과로 확정한 레버로 bull-drag 현금↓ → Conc CAGR↑. 게이트: **Conc CAGR ≥50% AND MaxDD ≥−25% AND OOS/IS < 7.66x.**

### Track 2 — 10Y proxy 트랙 (overfit 백신, 별도)
`docs/CODEX_INSTRUCTION_10Y_TRACK_20260620.md`의 **P0→P6** 그대로 실행:
- P0 proxy 라벨 락 → P1 멤버십 PIT proxy 파일(#1 blocker) → P2 가격캐시 연장 → P3 윈도우 풀리빌드(backtest_years=10) → P4 열화증거 수용 → P5 readiness 프리플라이트 → P6 10Y A/B.
- **데이터 갭 정직성**: ETF N-PORT는 ~2020 하드 floor(2016-2020 0%, 복구 불가), R1000 멤버십 PIT는 free 불가 → **모든 >7Y 산출물 `proxy` 라벨 강제, official 승격 금지.**
- P1에서 free PIT 멤버십 소스가 없으면 **멈추고 보고**(현재 IWB fallback = 생존편향).
- P6 성공 기준: **OOS/IS가 7Y baseline 7.66x보다 낮아질 것**.

---

## 6. 권장 착수 순서 (Codex)
1. **T1-b (Family B env-hook 추가)** — 작고 명확, T1-d unblock. 단일 PR.
2. **T1-c (C1 attribution)** — Family B 레버 특정.
3. 병행 **Track 2 P0→P1** — 멤버십 소스 조사 후 보고(여기가 진짜 관문).
4. T1-d, T1-a는 attribution 결과 + Family A 판정 후.

---

## 7. 하드 제약 (위반 금지)
- 측정/challenger 전용. **production target/cash/scoring mutation·promotion·live 금지.**
- env-hook 추가는 기본값 불변(측정 인프라). 정책 기본값 변경은 user 승인 전 금지.
- 모든 >7Y 산출물 `proxy` 라벨. official-10Y 승격 금지.
- 기존 메커니즘 재사용 — 새 membership/PIT/cash-overlay 코드 경로 발명 금지.
- 각 작업 = 단일 PR(draft), challenger 경로. **CHANGELOG 영어 + `HH:MM KST`**, `symbols_added/changed/config_fields_added/breaking_changes` 필드 채울 것.
- A1/A2(#216/#217)와 그 결과 판정은 Claude 담당 — 중복 dispatch 금지.
- 모든 floor·게이트 판정은 §0 acceptance contract 기준(절대 floor + 최대화).

---

## 8. Definition of done (트랙별)
- **7Y**: Main CAGR ≥35% AND MaxDD ≥−25% **동시**, Conc CAGR ≥50% AND MaxDD ≥−25%, 각각 baseline에서 한 레버씩 격리 측정 + user 승인. 이후 CAGR 최대화.
- **10Y**: proxy-10Y baseline 생성 + readiness가 `pit_universe_label` 단일 blocker로 축소 + 10Y A/B에서 OOS/IS < 7.66x.
