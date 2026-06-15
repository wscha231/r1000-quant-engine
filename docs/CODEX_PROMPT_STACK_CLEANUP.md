# Codex Prompt — Stack Cleanup + 3-Goal Supplement

> 이 문서는 **Codex에 그대로 붙여넣는 보완 prompt**입니다.
> `CODEX_PROMPT_48H_ACTION_PACK.md`를 **대체하지 않고 확장**합니다.
> 48h Action Pack은 실행 단위, 이 문서는 그 위의 **PR stack 정리 + 분기 strategic goal 보완**.
> 출처 brief: `CODEX_GOAL_SETTING_BRIEF.md`. 출처 데이터: `goals_20260615.yaml`, `ledger.jsonl`.

---

## 🟦 [PASTE TO CODEX FROM HERE] 🟦

Codex, 너는 이미 48h Action Pack을 받았다. 이 prompt는 그 위에서 **PR stack을 정리하고 분기 strategic goal 3개를 보완**한다. Replace가 아니라 SUPPLEMENT다.

---

## 0. 이 prompt의 범위

- ✅ Action Pack의 Actions 1-5 그대로 유효 (실행하라).
- ✅ 추가로: goals_20260615.yaml 보완 (stale + probability + new SG).
- ✅ 추가로: PR64/65/66/67 stack 정리 (의존성 + 머지 순서).
- ❌ Mission 재정의 금지 (35/50 unchanged).
- ❌ Action Pack의 location discipline 규칙 모두 그대로.
- ❌ master 직접 push 금지.

§0 [LOCAL]/[GITHUB]/[DRIVE] 태깅 규칙은 Action Pack과 동일하다. 모든 명령에 위치 태그.

---

## 1. 현재 검증된 사실 (Action Pack §2와 동일, 이번 prompt에서도 인용)

| Fact | Value | 검증 출처 |
|---|---|---|
| Bull-floor A/B verdict (run 27516185696) | **PASSED** | `[GITHUB]` `origin/claude/analyze-updated-code-OfEbu:cloud_results/performance_ledger/ledger.jsonl` row 3 |
| Main IS-CAGR | 21.45% → **22.90%** (+1.45pp) | 같음 |
| Main Tier-1 | full 35.20% / MDD -24.49% — **PASS** | 같음 |
| Conc IS-CAGR | 21.29% → **22.41%** (+1.12pp) | 같음 |
| Conc Tier-1 | full 44.43% / MDD -25.92% — CAGR FAIL 5.57pp gap | 같음 |
| Goals YAML current_state | STALE (21.45/21.29 — seed) | `[GITHUB]` `origin/codex/goals-2026-06-15:docs/proposals/goals_20260615.yaml` |
| Goals YAML probability_estimate | **0.50** (낙관, Claude verdict는 0.33) | 같음 |

검증은 Action Pack §5.1 verification preamble을 따라 직접 `[GITHUB]`에서 다시 확인하라.

---

## 2. PR Stack Map — 정리할 5개 PR

PR64/65/66/67을 user가 언급했다. 현재 상태와 의존성:

### 2.1 Current PR state

| PR | 브랜치 (head) | base | 상태 | 정체 |
|---|---|---|---|---|
| **#63** | `codex/github-agent-coordination-docs-20260615` | `master` | open | 문서 cross-agent coordination, 충돌 0 |
| **#64** | `codex/self-sustaining-loop-20260615` | `master` | open | 안전 루프 + ledger 재구현 + bull-floor 코드 |
| **#65** | `codex/goals-2026-06-15` | `codex/self-sustaining-loop-20260615` | draft | goals YAML — stale, probability 0.50 |
| **#66** (예정) | TBD — Action Pack 1+2+3+5 stack | `codex/self-sustaining-loop-20260615` | 미오픈 | bull-floor verdict + promote + router status |
| **#67** (예정) | TBD — Action Pack 4 + 이 prompt §4 보완 | `codex/goals-2026-06-15` | 미오픈 | goals YAML refresh |

### 2.2 Merge order — STRICT 의존성

```
T+0       PR#63 → master              (충돌 0, 가장 먼저)
T+24h     PR#66 stacks → PR#64        (Action Pack 1+2+3+5을 PR#64 위에 stack)
T+30h     PR#67 stacks → PR#65        (Action Pack 4 + §4 SG 보완을 PR#65 위에 stack)
T+36h     PR#64 + #66 → master        (한 번에 squash merge — codex/sustaining stack 전체)
T+42h     PR#65 + #67 → master        (goals YAML 채택, ChatGPT Pro 리뷰 후)
T+48h+    bull-floor default ON 효과 확인용 다음 A/B dispatch
```

**중요**: PR#66은 PR#64의 child branch가 아니라 **action sub-PR을 codex/self-sustaining-loop-20260615에 stack**하는 형태. 마지막에 PR#64 자체가 master로 squash merge되면 전체 stack이 한 번에 들어간다.

### 2.3 dependency 매트릭스

| 이 PR 머지하려면... | 먼저 해야 할 것 |
|---|---|
| PR#63 → master | 없음 (지금 가능) |
| PR#64 → master | PR#66 stack 완료 + ChatGPT Pro 리뷰 |
| PR#65 → master | PR#64 머지 완료 + PR#67 stack + 사용자 strategic 승인 |
| PR#66 | Action Pack Actions 1,2,3,5 모두 PR 오픈 + 검토 |
| PR#67 | Action Pack Action 4 + 이 prompt §4 보완 commit |

### 2.4 절대 안 할 것

- ❌ PR#65를 PR#64 머지 전에 master로 머지 — base가 codex/sustaining이므로 끊김.
- ❌ Claude 브랜치 (`origin/claude/analyze-updated-code-OfEbu`)를 PR#66이나 #67 base로 사용 — 옛 master 기반.
- ❌ 각 Action을 따로따로 master로 머지 — stack 깨짐.

---

## 3. Goals YAML 보완 — 신규 Strategic Goal 3개 추가

`docs/proposals/goals_20260615.yaml`에 다음 SG를 추가하라. PR#67에 포함.

### 3.1 SG-2026Q3-03 — Cross-Agent Coordination Discipline

기존 SG-01 (IS-CAGR), SG-02 (self-correction loop)는 유지. 신규:

```yaml
strategic_goals:
  - id: SG-2026Q3-03
    title: Establish cross-agent location discipline + goal-setting framework
    horizon: 2026-Q3 (2026-07-01 to 2026-09-30)
    contributes_to: mission.process_integrity
    rationale: |
      Claude Code, Codex, ChatGPT Pro 세 agent가 같은 repo를 만지는데
      누가 [LOCAL] / [GITHUB] / [DRIVE] 중 어디서 작업하는지 모호하면
      stale read, write 충돌, ledger 오염 위험. 48h Action Pack의 일회성
      규율을 분기 단위 strategic으로 격상해야 자연소멸 안 함.

    success_kpis:
      - kpi: location_tag_compliance_in_agent_outputs
        target_min_ratio: 0.95
        source: "manual sampling of last 20 agent responses; auto-grep [LOCAL]/[GITHUB]/[DRIVE] prefix presence"
        baseline: 0.30  # 보수적 추정 (현재 비공식)
      - kpi: brief_documents_committed_to_master
        target_count: 4  # CODEX_GOAL_SETTING_BRIEF, CODEX_PROMPT_NEXT_GOALS, CODEX_PROMPT_48H_ACTION_PACK, AGENT_COORDINATION
        source: "git ls-tree -r origin/master --name-only | grep -c 'docs/(CODEX|AGENT_COORD)'"
        baseline: 0  # master에 아직 없음
      - kpi: ledger_schema_unification_done
        target: true
        source: "docs/proposals/ledger_reconciliation_20260615.md exists on master"
        baseline: false
      - kpi: pr_chain_violations_detected
        target_max: 0
        source: "any PR base != documented base in merge order table"

    failure_criteria:
      - "By 2026-Q3 end, fewer than 4 brief docs on master"
      - "Any agent run (sampling) shows < 80% location tag compliance"
      - "Two divergent ledger.jsonl versions persist beyond 2026-07-15"

    probability_estimate: 0.80  # mostly mechanical, low risk
    probability_reasoning: |
      이 SG는 새 코드 alpha 없이 문서 + PR 위생 작업. 위험은 "사람이 안
      따른다"는 사회적 위험 뿐. Claude session에서 이미 4개 brief 문서를
      생성했으므로 master 머지만 하면 60% 달성.

    dependencies:
      - PR #63 머지 (cross-agent coordination 문서들이 master에 안착)
      - Action Pack Action 1 (ledger reconciliation)

    decomposes_into:
      - TG-WK24-LOCATION-COMPLIANCE-AUDIT
      - TG-WK25-BRIEF-DOCS-TO-MASTER
      - TG-WK25-LEDGER-UNIFY-FINAL
```

### 3.2 SG-2026Q3-01 보완 (기존 update — Action Pack Action 4와 함께 PR#67에 포함)

```yaml
strategic_goals:
  - id: SG-2026Q3-01
    # ... 기존 필드 유지 ...
    probability_estimate: 0.33   # was 0.50; bull-floor verdict 반영
    probability_reasoning: |
      Verified by bull-floor A/B (run 27516185696):
      - Single structural fix lifted Main IS +1.45pp, Conc IS +1.12pp.
      - To reach SG-2026Q3-01 targets (Main 28%, Conc 32%), we need
        5-8 such fixes cumulatively. Historically half wash or regress
        (T3, T4, conc-hysteresis).
      - The only single lever large enough to bridge the gap is era-aware
        sub-model (Finding F1). Its E1 IC-analysis GO/NO-GO gate has
        not been run. 8y bootstrap is evidence-only (~+0.5pp).
      - Honest estimate 0.33 reflects this (was 0.50 — Codex initial,
        per Claude verdict revision 2026-06-15).

    update_history:
      - { at: 2026-06-15, by: claude_verdict, from: 0.50, to: 0.33, reason: bull_floor_ceiling_evidence }

    additional_kpis:
      - kpi: bull_floor_default_on
        target: true
        source: "tools/run_alphaops_vnext_policy_replay.py phase_is_enabled('regime_capacity_bull_floor') default"
        baseline: false  # currently default OFF
      - kpi: era_e1_ic_analysis_completed
        target: true
        source: "outputs/per_era_ic/<era>_summary.md files exist"
        baseline: false
```

### 3.3 SG-2026Q3-02 보완 (self-correction queue closure — 기존 SG 확장)

```yaml
strategic_goals:
  - id: SG-2026Q3-02
    # ... 기존 필드 유지 ...
    decomposes_into:
      - TG-WK24-DUPLICATE-SUPPRESSION    # Action Pack Action 5에 포함
      - TG-WK24-STATUS-COLUMN            # Action Pack Action 5에 포함
      - TG-WK25-STALE-DETECTION
      - TG-WK25-AB-RESULT-VERIFIER
      - TG-WK26-PR-PAYLOAD-GENERATION

    additional_failure_criteria:
      - "Router status column not present in workflow_dispatch_payloads.json by 2026-06-21"
      - "Duplicate payload accepted twice within same week"
```

---

## 4. Action Pack Action 4 보완 — Goals YAML 갱신 시 추가 항목

48h Action Pack의 Action 4는 current_state와 probability만 갱신했다. 이 prompt에서 다음을 추가하라:

### 4.1 추가할 metadata 필드

```yaml
metadata:
  # 기존 필드 유지...
  bull_floor_verdict:
    run_id: "27516185696"
    commit: "cd480423"
    landed_at: 2026-06-15
    result: PASS
    main_is_cagr_delta_pp: 1.45
    conc_is_cagr_delta_pp: 1.12
    main_mdd_delta_pp: 1.44  # 개선
    conc_mdd_delta_pp: -0.04  # wash
    next_action: promote_to_default_ON  # Action Pack Action 3

  pr_stack_state:
    pr_63: { branch: codex/github-agent-coordination-docs-20260615, base: master, status: open, target_merge_t: T+0_24h }
    pr_64: { branch: codex/self-sustaining-loop-20260615, base: master, status: open, target_merge_t: T+36h, depends_on_pr: [66] }
    pr_65: { branch: codex/goals-2026-06-15, base: codex/self-sustaining-loop-20260615, status: draft, target_merge_t: T+42h, depends_on_pr: [64, 67] }
    pr_66_planned: { will_stack_actions: [1,2,3,5], target_open: T+24h }
    pr_67_planned: { will_stack_actions: [4, this_prompt_sg], target_open: T+30h }

  honest_baseline_caveat: |
    Bull-floor A/B 측정 결과 단일 fix 천장 ~1pp 확인.
    CLAUDE.md 35/50 targets은 (a) era-aware sub-model 돌파 또는
    (b) 현 OOS-inflated headline이 진짜 천장임을 인정한 후 contract
    revision 둘 중 하나가 필요. (b)는 사용자 미비준 — 35/50 유지.

  target_conflict_flag: |
    30/-25, 50/-28 완화안은 일부 계획 문서에 언급되나 사용자 미비준.
    이 proposal은 CLAUDE.md 35/50 유지.

  cross_agent_coordination_status:
    claude_code_brief: docs/CODEX_GOAL_SETTING_BRIEF.md  # 작성 완료, master 미머지
    next_goals_prompt: docs/CODEX_PROMPT_NEXT_GOALS.md   # 작성 완료, master 미머지
    action_pack_48h: docs/CODEX_PROMPT_48H_ACTION_PACK.md  # 작성 완료, master 미머지
    stack_cleanup_supplement: docs/CODEX_PROMPT_STACK_CLEANUP.md  # 이 prompt 자체, master 미머지
    chatgpt_pro_handoff: SESSION_HANDOFF_20260615.md
    agent_coordination_doc: docs/AGENT_COORDINATION.md  # PR#63에 포함
```

### 4.2 새 anti_goals 항목 추가

```yaml
anti_goals:
  # 기존 anti_goals 유지...
  - "Merging PR#65 to master before PR#64 (base broken)"
  - "Whole-merging Claude branch instead of cherry-picking specific items"
  - "Setting bull_floor default OFF after verdict PASS (would waste verified +1pp)"
  - "Promoting any future signal without dual verification (Tier-2 strengthened_pass + IMPROVING streak ≥ 2)"
  - "Skipping location tag in agent commands (compliance KPI tracked)"
```

---

## 5. 새 Tactical Goals (Action Pack Actions와 매핑)

기존 tactical_goals에 다음을 추가하라. 각각 어느 Action에 매핑되는지 명시.

```yaml
tactical_goals:
  # 기존 6개 tactical_goals 유지...

  - id: TG-WK24-LEDGER-UNIFY
    title: Two-ledger reconciliation document
    horizon: 2026-W24 (2026-06-15~21)
    contributes_to: SG-2026Q3-03
    maps_to_action_pack: Action 1
    success_kpis:
      - kpi: reconciliation_md_pr_opened
        target: true
        source: "[GITHUB] gh pr list --search 'ledger reconciliation'"
    deadline: 2026-06-16
    owner: codex

  - id: TG-WK24-BULL-FLOOR-DATA-PORT
    title: Port bull-floor verdict row to codex ledger
    maps_to_action_pack: Action 2
    success_kpis:
      - kpi: codex_ledger_row_count
        target: 3
        source: "[GITHUB] codex/self-sustaining-loop-20260615:cloud_results/performance_ledger/ledger.jsonl"
        baseline: 2
    deadline: 2026-06-16
    owner: codex

  - id: TG-WK24-BULL-FLOOR-PROMOTE
    title: Bull-floor default OFF → ON
    maps_to_action_pack: Action 3
    contributes_to: SG-2026Q3-01
    success_kpis:
      - kpi: bull_floor_default_on
        target: true
        source: "tools/run_alphaops_vnext_policy_replay.py default arg"
    failure_criteria:
      - "smoke regression on Tier-2 strengthened gate"
    deadline: 2026-06-17
    owner: codex

  - id: TG-WK24-GOALS-REFRESH
    title: Update goals YAML with verified verdict + honest probability
    maps_to_action_pack: Action 4 + 이 prompt §3+§4
    contributes_to: SG-2026Q3-03
    success_kpis:
      - kpi: goals_current_state_matches_ledger
        target: true
        source: "goals_20260615.yaml metadata.current_state vs ledger row 3"
    deadline: 2026-06-17
    owner: codex

  - id: TG-WK24-ROUTER-STATUS
    title: Router duplicate suppression + status column
    maps_to_action_pack: Action 5
    contributes_to: SG-2026Q3-02
    success_kpis:
      - kpi: router_queue_has_status_column
        target: true
        source: "router_queue.json schema"
      - kpi: duplicate_enqueue_blocked
        target: true
        source: "tests/self_correction_router_smoke.py"
    deadline: 2026-06-21
    owner: codex

  - id: TG-WK24-PR-STACK-VERIFY
    title: PR64/65/66/67 dependency chain audit
    contributes_to: SG-2026Q3-03
    success_kpis:
      - kpi: pr_base_table_matches_planned
        target: true
        source: "[GITHUB] each PR's base branch matches §2.2 merge order"
      - kpi: pr_66_67_opened
        target: true
        source: "[GITHUB] gh pr list state=open"
    deadline: 2026-06-21
    owner: codex
```

---

## 6. Action Pack과의 통합 — Codex 실행 순서 (수정)

이 prompt 받은 후 Codex의 실제 작업 순서:

```
[GITHUB] gh pr list --repo wscha231/r1000-quant-engine
  → 현재 PR 상태 확인. PR#63/#64/#65 open 확인.

[LOCAL] git fetch origin
  → 5 브랜치 SHA 재확인.

[작업 1] Action Pack Action 1 실행
  → PR#66 stack 1번째: codex/ledger-reconciliation-20260615
  → base: codex/self-sustaining-loop-20260615

[작업 2] Action Pack Action 2 실행
  → PR#66 stack 2번째: codex/port-bull-floor-row
  → base: codex/ledger-reconciliation-20260615 (이전 PR 위에 stack)

[작업 3] Action Pack Action 3 실행
  → PR#66 stack 3번째: codex/promote-bull-floor
  → base: codex/port-bull-floor-row

[작업 4] Action Pack Action 5 실행 (Action 4는 별도 stack)
  → PR#66 stack 4번째: codex/router-status-column
  → base: codex/promote-bull-floor

  → 이 4개를 합쳐 "PR#66 stack"이라 부른다.

[작업 5] Action Pack Action 4 + 이 prompt §3+§4 실행 (PR#67 stack)
  → 브랜치: codex/goals-update-bull-floor
  → base: codex/goals-2026-06-15
  → 변경: §4의 metadata + §3의 SG-2026Q3-03 추가 + 기존 SG update_history + decomposes_into

[작업 6] PR stack verify
[GITHUB]
  → gh pr list로 PR#66 stack 4개 + PR#67 1개 = 5개 신규 PR open 확인
  → 각 PR의 base가 §2.2 merge order와 일치하는지 확인
  → 미스매치면 escalate

[작업 7] ChatGPT Pro에 리뷰 요청
  → PR#66 stack: 4개 PR을 순서대로 리뷰 (특히 promote PR의 smoke)
  → PR#67: probability 0.33 + SG-2026Q3-03 신규의 적절성
  → PR description에 "@chatgpt-pro review requested" 명시 (or 사용자가 별도 알림)

[작업 8] STOP, await user merges
  → Codex는 어떤 PR도 self-merge 금지
  → PR#63 → master는 user
  → PR#66 stack → PR#64 → master는 user + ChatGPT Pro
  → PR#65 + PR#67 → master는 user + ChatGPT Pro + strategic 승인
```

---

## 7. 출력 형식 — 이번 prompt 전용 추가

48h Action Pack §5의 출력 형식 (verification preamble, per-command location tag, end acknowledgment) 모두 그대로. 추가로:

### 7.1 PR stack status block (작업 종료 시)

```
PR Stack State Report — <UTC timestamp>

PR#63 → master                    : open, mergeable=<bool>
PR#64 → master                    : open, blocked by PR#66 stack
PR#65 → codex/sustaining          : draft, blocked by PR#67
PR#66 stack (will → PR#64):
  Sub-PR 1: codex/ledger-reconciliation-20260615 -> codex/sustaining          : <url> open
  Sub-PR 2: codex/port-bull-floor-row -> codex/ledger-reconciliation-...      : <url> open
  Sub-PR 3: codex/promote-bull-floor -> codex/port-bull-floor-row             : <url> open
  Sub-PR 4: codex/router-status-column -> codex/promote-bull-floor            : <url> open
PR#67 → codex/goals-2026-06-15    : codex/goals-update-bull-floor-and-sg03    : <url> open

Critical path: PR#63 (T+0) → PR#66 stack squash to PR#64 (T+36h) → PR#65+#67 (T+42h)
Open dependencies: ChatGPT Pro review on PR#66 promote + PR#67 probability change.
```

### 7.2 End acknowledgment 확장

```
I read CODEX_PROMPT_48H_ACTION_PACK.md (Actions 1-5) + this Stack Cleanup
Supplement (§§1-7). I verified branch SHAs at [GITHUB] via gh api.

Executed:
  Action 1: <url>  (ledger reconciliation note, PR#66 stack base)
  Action 2: <url>  (port bull-floor row, stacks on Action 1)
  Action 3: <url>  (promote bull-floor default ON, stacks on Action 2)
  Action 5: <url>  (router status column, stacks on Action 3)
  Action 4 + Supplement §3+§4: <url>  (PR#67 = goals YAML refresh + new SG)

PR stack:
  PR#66 stack 4 sub-PRs → merge target codex/self-sustaining-loop-20260615
    → which becomes PR#64 → master
  PR#67 → codex/goals-2026-06-15 (PR#65)
    → which becomes PR#65 → master AFTER PR#64

Location compliance: all 8 commits include [LOCAL] tag in workflow.
All PRs awaiting user / ChatGPT Pro review. No self-merge.

Next: monitor PR statuses, report if any base/dependency drift detected.
```

---

## 8. Anti-patterns (Action Pack §6 보강)

| Anti-pattern | 추가 검출 |
|---|---|
| 4개 Action을 단일 PR로 묶기 | PR#66 stack은 **4개 sub-PR**, 합치면 리뷰 불가 |
| Action 4를 PR#66 stack에 포함 | Action 4는 goals YAML이므로 **PR#65 stack**, base 다름 |
| PR#67을 PR#64 위에 base | PR#67은 goals — base는 codex/goals-2026-06-15 (PR#65 branch) |
| stale PR description | PR#65에 bull-floor verdict 반영 안 한 채로 ChatGPT Pro 리뷰 요청 |
| Mission target 직접 수정 | YAML mission 블록의 35/50 직접 변경 금지 (Mission immutable) |
| location tag 누락 | 모든 command가 [LOCAL]/[GITHUB]/[DRIVE] 시작해야 |

---

## 9. Escalation Triggers (Action Pack §7 추가)

다음 조건 시 즉시 사용자/ChatGPT Pro에 알림:

- PR#64 또는 PR#65가 codex의 stack 작업 전에 이미 머지된 상태로 발견되면 → master 기준으로 stack 재구성 필요.
- Action 1 reconciliation에서 두 ledger 스키마가 **호환 불가**로 판명되면 → SG-2026Q3-03의 ledger_unify KPI 위험, design re-review 필요.
- Bull-floor promote PR이 smoke 회귀 → Action 3 hold, smoke fail 원인 분석.
- PR#67 probability 0.33이 ChatGPT Pro에서 또 reject되면 → Claude verdict 재확인.
- 새 user request가 stack 작업과 충돌하면 → 이 prompt 일시 중단, 새 우선순위 확인.

---

## 10. End acknowledgment (위 §7.2 형식 그대로 사용)

작업 완료 후 §7.2 acknowledgment 출력. URL이 모두 채워졌는지 확인 후 사용자에게 보고.

🟦 [END OF PROMPT — Codex starts here] 🟦

---

## 사용 방법 (메타-노트, Codex에 붙이지 마세요)

1. 🟦 [PASTE TO CODEX FROM HERE] 🟦 ~ 🟦 [END OF PROMPT — Codex starts here] 🟦 사이를 복사.
2. **48h Action Pack을 이미 Codex가 받은 상태에서** 추가로 이 prompt를 던지기.
3. Codex의 verification preamble + 5개 PR open 확인 (PR#66 stack 4개 + PR#67 1개).
4. PR base 매트릭스가 §2.2와 일치하는지 사용자가 확인.
5. ChatGPT Pro에 PR#66 stack의 promote sub-PR과 PR#67의 probability 변경을 리뷰 요청.
6. 사용자가 PR#63 → master, PR#66 stack 머지 → PR#64 → master, PR#67 → PR#65 → master 순으로 실행.

## 위치 규율을 분기 strategic으로 격상하는 이유

지금까지의 brief 4개 + Action Pack은 **per-task 규율**. 분기 끝나면 자연소멸. SG-2026Q3-03은 이걸 **measurable KPI로 격상**해서:
- 4개 brief 문서가 master에 머지되는지 (commitment 증명)
- agent 응답 sample에서 location tag compliance >95%인지 (실제 준수)
- ledger 스키마 통일 완료인지 (가장 큰 위생 리스크)

세 KPI가 측정되면 분기 후에도 살아남는다.

## ChatGPT Pro 리뷰 시 push back 예상

- "probability 0.33이 너무 보수적이지 않나?" → Claude verdict 근거 인용 + bull-floor +1pp 천장 데이터 제시.
- "SG-2026Q3-03이 너무 process-heavy하지 않나?" → location tag 누락이 곧 ledger 오염 위험 = alpha 손실로 이어진다는 인과 설명.
- "PR#66 stack을 4개로 쪼개는 게 과한가?" → 각 PR이 다른 코드 영역 (ledger / data / promote / router) 만지므로 리뷰 분리가 안전.

---

**End of Codex Stack Cleanup + Goal Supplement Prompt — 2026-06-15 14:00 UTC**

Maintainer: Claude Code.
Update protocol: 다음 분기 시작 전 (SG-2026Q3-* 모두 마감) 또는 새 PR stack 생성 시 재작성.
