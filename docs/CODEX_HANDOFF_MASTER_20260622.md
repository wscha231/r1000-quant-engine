# Codex 마스터 핸드오프 — 2026-06-22 (Family B 현금드래그 + lever sweep 트랙)

- 작성일: 2026-06-22 KST / 작성: Claude
- repo: `wscha231/r1000-quant-engine` — https://github.com/wscha231/r1000-quant-engine
- 작업·PR 브랜치: **`claude/pr146-review-analysis-6dkvd8`** → PR #147 https://github.com/wscha231/r1000-quant-engine/pull/147
- **이 문서가 현행 단일 진입점.** 이전 `docs/CODEX_HANDOFF_MASTER_20260620.md`를 대체(supersede). §0/§6은 0620에서 유효 계승, §1~§4는 그 이후 변경분.

---

## 0. Mission + Acceptance contract (불변, user 지시)

**아래는 "최소 달성치(절대 floor)". 넘기는 게 끝이 아니라, 넘긴 뒤 더 높이는 게 목표.**

| | 최소 floor (절대) | stretch |
|---|---|---|
| **Main CAGR** | **≥ 35%** | 높을수록 |
| **Main MaxDD** | **≥ −25%** (더 얕게) | −25%보다 얕게 |
| **Conc CAGR** | **≥ 50%** | 높을수록 |
| **Conc MaxDD** | **≥ −25%** | −25%보다 얕게 |

- floor는 **절대 기준**(baseline 대비 델타 아님). baseline보다 좋아져도 floor 미달이면 reject.
- broker-ledger next-close 기준만 official (CLAUDE.md 데이터 계약).
- 검증된 7Y baseline = run #214 `27873592126` (master `a3dbd01`): Main 34.73% CAGR / −26.05% MDD / cash 26.4%; Conc 45.47% CAGR / −24.59% MDD / cash 41.9% / OOS-IS 7.66x.

---

## 1. 0620 이후 업데이트 내역 (commit + 판정, 시간순)

| commit | 내용 | 상태 |
|---|---|---|
| `1b18955` | **Family B 현금드래그 env hooks 노출** (`r1000_config.py`, fast_crash_env_override 화이트리스트 확장) | merged (Codex) |
| `7143924` | **Family A 판정 doc** (`docs/FAMILY_A_VERDICT_20260621.md`) | merged |
| `acb2136` | **daily-stop position-risk replay를 operating_minimal 사이드카로 승격** (`tools/run_full_rebuild_sidecars.py`) — env `R1000_DAILY_STOP_HARD_STOP`/`R1000_DAILY_STOP_TRAILING_STOP` | merged |
| `54be78d` | **C-floor 레버 (진짜 Family B 레버)**: `R1000_CONC_GROSS_CAP_FLOOR` → concentrated benchmark-guard gross cap을 env로 올림 (`r1000_market_leader_engine.py`) | merged |
| `6ca5b35` | **단일-런 lever sweep 하니스** (`tools/run_lever_sweep.py`) — 한 리빌드로 conc-gross floor grid + daily-stop grid 전체 측정. 사이드카에 opt-in(`R1000_LEVER_SWEEP=1`) | merged |

### 1a. Family A 판정 = FAIL (월간 cash-overlay는 Main MDD에 죽은 길)
- runs: A1 #216 `27887125658`(DD breaker), A2 #217 `27887129839`(VIX floor) — 둘 다 completed/success.
- **A1 ≈ A2** (Main MDD −27.18% 동일, CAGR 34.27% 동일), avg_cash 불변(26.6%), Main MDD 오히려 악화 → 가설 반증.
- 근본원인: COVID 급락 = 28일(2020-02-19→03-18) < 월간 리밸런스 주기. 사후반응형 월간 overlay는 선제 방어 불가. **"현금 레버 더 세게" 방향은 Main MDD에 무효.** 선제 de-risk(dd-velocity)류만 유효.
- 부수 결론: **Conc 결함은 MDD 아니라 CAGR shortfall(−5.6pp)** → Family B(bull cash drag, avg_cash 41.9%) 영역. 전문은 `docs/FAMILY_A_VERDICT_20260621.md`.

---

## 2. 진행 중 / 방금 끝난 런 (2026-06-22 ~03:00Z 기준)

URL 패턴: `https://github.com/wscha231/r1000-quant-engine/actions/runs/<run_id>`

| run_id | sha | 측정 대상 | 상태 | 산출 경로 |
|---|---|---|---|---|
| `27926056802` | `6ca5b35` | **lever sweep** (conc-gross floor {0.0,0.7,0.8,0.9} + daily-stop grid) | **running ~06:40Z 종료예정** | `outputs/lever_sweep/summary.json`, `sweep_report.md` |
| `27924395094` | `54be78d` | C-floor=0.70 단일 arm | running ~05:40Z | broker-ledger 메트릭 (아티팩트) |
| `27919702107` | `acb2136` | daily-stop tight `-0.10/-0.15` | **FAILED (push-race)** — 메트릭은 아티팩트에 있음 | `user-operating-minimal-...-27919702107` |
| `27919701106` | `acb2136` | daily-stop baseline(기본 stop) | **FAILED (push-race)** — 메트릭은 아티팩트에 있음 | `user-operating-minimal-...-27919701106` |

- **두 daily-stop 실패는 컴퓨트 실패 아님** — 리빌드 성공·아티팩트 정상 업로드. git push 단계의 autostash rebase 충돌(§3)로 commit 실패했을 뿐. **sweep 런이 daily-stop grid를 어차피 커버**하므로 재실행 불필요.
- C-floor 단일 arm도 sweep의 floor grid에 포함되어 중복 → push 실패해도 무방.

---

## 3. ⚠ 인프라 블로커 2개 (codex 필독 — 결과 전달 경로)

이 원격 환경에서 **런 결과를 끌어오는 두 경로가 모두 제약**된다:

1. **git push race (workflow 버그).** 장시간 리빌드 중 브랜치가 전진하면(봇 `[skip ci]` outputs/ 커밋 또는 신규 feature 커밋) 결과-push 단계의 `git rebase --autostash origin/branch`가 `outputs/`에서 충돌 → `fatal: unresolved conflict` → exit 128 → 런이 "failure"로 찍힘. **단, push가 거부될 때만(=origin이 전진했을 때만) 이 fragile 경로로 진입.** origin이 그대로면 attempt-1에서 clean push 됨.
   - **함의: in-flight 런이 있는 동안 브랜치에 아무것도 push하지 마라.** push하면 그 런들의 clean-push 경로를 깨서 결과가 브랜치에 안 올라온다.
   - 수정 필요(미래 런용): push 단계에서 autostash 충돌 시 `outputs/` 자동 해소(예: 충돌 시 run 측 outputs/ 채택 후 `git add -A`). **단, 현재 in-flight 4개가 다 끝난 뒤에 수정 push할 것.**
2. **아티팩트 blob 호스트 차단.** GitHub MCP는 다운로드 URL만 주고, 그 URL은 `*.blob.core.windows.net`(Azure)인데 **이 환경 egress allowlist에 없어 curl 403**. 즉 push-fail한 런의 메트릭을 아티팩트에서 직접 못 끌어온다.
   - 해소하려면 user가 환경 egress 설정에 `*.blob.core.windows.net` 추가해야 함. (안 하면 push-fail 런 결과는 회수 불가.)

**현재 신뢰 가능한 결과 전달 경로 = sweep 런(`27926056802`)의 clean push 하나뿐.** origin이 `6ca5b35`에 머무는 한(=추가 push 금지) sweep 종료 시 `outputs/lever_sweep/`가 브랜치에 올라오고 `git pull`로 읽힌다.

---

## 4. 앞으로 계획 (우선순위)

1. **[Claude, 진행 중] sweep 결과 회수·판정.** sweep 착지(~06:40Z) 후 `git pull` → `cloud_results/full_rebuild/latest_global_alpha_universe/lever_sweep/summary.json`(또는 `outputs/lever_sweep/`) 읽어 conc-gross floor별 Conc CAGR/MaxDD/avg_cash + daily-stop별 Main/Conc MaxDD 비교 → Family B 판정.
2. **[Claude] workflow push-race 수정** — §3-1. **sweep 착지 후** 단일 PR로 push.
3. **[Codex] Family B A/B (T1-d)** — sweep이 가리키는 최적 conc-gross floor를 baseline 대비 단일 레버로 격리 측정. 게이트: **Conc CAGR ≥50% AND MaxDD ≥−25% AND OOS/IS < 7.66x.** env: `R1000_CONC_GROSS_CAP_FLOOR`.
4. **[Codex] Main CAGR-lift 레버 (T1-a)** — Family A로 Main MDD는 월간 overlay로 못 줄임이 확정 → Main floor 동시충족은 **CAGR↑ 레버 + 선제 de-risk**가 필요. attribution으로 Main CAGR 손실원 특정 후 단일 레버 A/B. 게이트: Main CAGR ≥35% AND MaxDD ≥−25% 동시.
5. **[Codex] Track 2 — 10Y proxy** (`docs/CODEX_INSTRUCTION_10Y_TRACK_20260620.md` P0→P6 유지, overfit 백신).

---

## 5. 경로·주소 레퍼런스

- 엔진/설정: `r1000_config.py`(env-override hook), `r1000_market_leader_engine.py`(C-floor gross cap), `r1000_top30_institutional.py`(메인 엔진)
- sweep 하니스: `tools/run_lever_sweep.py` (`--dry-run`으로 명령 검증 가능), 사이드카 wiring: `tools/run_full_rebuild_sidecars.py` (opt-in `R1000_LEVER_SWEEP=1`, floors/grid는 `R1000_LEVER_SWEEP_FLOORS`/`R1000_LEVER_SWEEP_DAILY_STOP`로 override)
- daily-stop 사이드카: `tools/run_full_rebuild_sidecars.py` (`R1000_DAILY_STOP_HARD_STOP`/`_TRAILING_STOP`)
- vNext target-book 빌드: `tools/run_alphaops_vnext_policy_replay.py`, broker-ledger: `tools/run_broker_ledger_replay.py`, daily-stop replay: `tools/run_broker_position_risk_replay.py`
- 판정/베이스라인 doc: `docs/FAMILY_A_VERDICT_20260621.md`, `docs/RUN214_BASELINE_CONFIRMED_20260620.md`, `docs/CODEX_AB_EXECUTION_7Y_CAGR_MDD_20260620.md`
- 워크플로: `.github/workflows/full_rebuild_manual.yml` (입력 `universe_mode`/`backtest_years`/`skip_collector`/`fast_mode`/`sidecar_profile`/`experiment_env_json`)
- 결과 위치: 성공 런 → `cloud_results/full_rebuild/latest_global_alpha_universe/`; 실패 런 진단 → `cloud_results/full_rebuild/failed_runs/<run_id>_global_alpha_universe/`(단 push 성공 시에만 브랜치에 존재); 아티팩트명 `official-broker-ledger-...-<run_id>` / `user-operating-minimal-...-<run_id>`

---

## 6. 하드 제약 (위반 금지, 0620 계승)

- 측정/challenger 전용. **production target/cash/scoring mutation·promotion·live 금지.**
- env-hook 추가는 기본값 불변(측정 인프라). 정책 기본값 변경은 user 승인 전 금지.
- A/B 주입: ref = 이 브랜치, `experiment_env_json` JSON, 키 정규식 `^(PHASE_|R1000_|ALPHAOPS_)[A-Z0-9_]+$`. ceteris-paribus 위해 빈 cache_key_suffix + backtest_years=7 + global_alpha_universe + skip_collector=true.
- **in-flight 런 있는 동안 브랜치 push 금지**(§3-1).
- 각 작업 = 단일 PR(draft), challenger 경로. **CHANGELOG 영어 + `HH:MM KST` + `symbols_added/changed/config_fields_added/breaking_changes`.**
- in-flight 4개 런(`27926056802`/`27924395094`/`27919702107`/`27919701106`) 판정은 Claude 담당 — 중복 dispatch 금지.
- 모든 floor·게이트 판정은 §0 절대-floor 기준.
