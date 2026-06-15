# Codex Prompt — paste this to ask Codex for the next goal set

> 이 문서는 **Codex에 그대로 붙여넣는** prompt입니다.
> 사용자가 Codex 채팅 또는 dispatch에 복붙해서 다음 분기/스프린트 목표 제안을 받습니다.
> 출처: `docs/CODEX_GOAL_SETTING_BRIEF.md` (정식 brief).
> 별도 추가 컨텍스트 없이 이 prompt만으로 cold start 가능합니다.

---

## 🟦 [PASTE TO CODEX FROM HERE] 🟦

Codex, you are the parallel-breadth agent on the r1000-quant-engine project. The user is asking you to propose the next set of goals for the project. Follow the protocol below exactly.

### Repository

- **Repo**: `https://github.com/wscha231/r1000-quant-engine` (private)
- **Default branch**: `master`
- **Your work branch**: create new `codex/goals-2026-06-15`
- **Target PR base**: `master` (after the in-flight `codex/self-sustaining-loop-20260615` PR #64 merges; if you're proposing goals BEFORE that merge, base off `codex/self-sustaining-loop-20260615` directly so your goals reference the latest dispatcher/router contracts)

### Read these first, in this order (do not skip; do not summarize from memory)

1. **`docs/CODEX_GOAL_SETTING_BRIEF.md`** — your authority limits, the 4-level goal hierarchy, the 5-category KPI framework, the mandatory YAML output schema, the 10 hard prohibitions. Re-read §0 (your authority), §3 (KPI categories), §6.2 (the YAML schema you MUST produce), §9 (10 hard prohibitions).
2. **`SESSION_HANDOFF_20260615.md`** — current state, P0/P1/P2/P3 priorities, role split. Specifically §0 (active inbox), §2 (next steps with role split), §3 (DO/DON'T rules).
3. **`SYSTEM_INTEGRATION_ANALYSIS_20260615.md`** — six surfaces audited, Findings F1-F6. Pay attention to F1 (era-leadership not in code), F2 (crisis 1-30d lag), F3 (174 `production_activation_allowed:false` flags), F4 (OOS-inflated headlines), F5 (portfolio_policy footgun, already fixed), F6 (7.03y vs 8y data shortfall).
4. **`CLAUDE.md`** — immutable mission targets: Main CAGR ≥ 35% / MDD ≥ -25%, Concentrated CAGR ≥ 50% / MDD ≥ -25%, broker_ledger_next_close, ≥ 8y window.
5. **`docs/ALPHAOPS_DATA_SYSTEM_CONTRACT.md`** — the data-first contract. Do not propose any goal that violates it.
6. **`CHANGELOG.md`** last ~500 lines — most recent decisions (this session shipped Tier-2 gates, IS attribution, performance ledger, P0a bull-floor, weekly cron, and the system integration audit).

### Fetch THESE 7 data sources before writing (do NOT use cached values from this prompt; verify yourself and report deltas)

```bash
# 1. Ledger trend — most important
cat cloud_results/performance_ledger/ledger.jsonl | tail -5
cat cloud_results/performance_ledger/latest_verdict.json

# 2. Current official metrics
cat cloud_results/full_rebuild/latest_global_alpha_universe/account_evaluation/official_metrics.json

# 3. IS attribution leak tags (which years are the leaks?)
cat cloud_results/full_rebuild/latest_global_alpha_universe/is_attribution/concentrated_summary.md
cat cloud_results/full_rebuild/latest_global_alpha_universe/is_attribution/main_summary.md

# 4. 8-year data readiness
ls outputs/eight_year_readiness/ 2>/dev/null
cat outputs/eight_year_readiness/summary.json 2>/dev/null
cat outputs/data_readiness/summary.json | head -200

# 5. Broker replay window length (the F6 metric)
cat cloud_results/full_rebuild/latest_global_alpha_universe/broker_replay/main/metrics.json | python3 -c "import sys,json; d=json.load(sys.stdin); print('main years=', d.get('years'), 'start=', d.get('start_date'), 'end=', d.get('end_date'))"

# 6. portfolio_system_guard hard errors
cat outputs/portfolio_system_guard/error_check.json 2>/dev/null
cat cloud_results/full_rebuild/latest_global_alpha_universe/portfolio_system_guard/error_check.json

# 7. Bull-floor A/B verdict (the just-completed P0.1 run 27516185696)
# Expect a new ledger row for commit cd480423; if not present, flag it.
grep "cd480423\|27516185696\|bull_floor" cloud_results/performance_ledger/ledger.jsonl
```

### Current state — as observed by this Claude session at 2026-06-15 10:30 KST (verify these)

| Metric | Value | Source |
|---|---|---|
| Ledger rows | 2 seed + ≥1 new (cd480423 bull-floor A/B should have landed) | `ledger.jsonl` |
| Main IS-CAGR | 21.45% (pre-bull-floor; verify post-A/B) | seed row 27498401423 |
| Conc IS-CAGR | 21.29% (pre-bull-floor; verify post-A/B) | seed row 27498401423 |
| Main full CAGR | 34.33% (Tier-1 gap -0.67pp) | account_evaluation |
| Conc full CAGR | 44.57% (Tier-1 gap -5.43pp) | account_evaluation |
| OOS/IS ratio Main | 3.53x (Tier-2 fail, cap 3.0x) | tier2_gates |
| OOS/IS ratio Conc | 6.08x (Tier-2 fail) | tier2_gates |
| Broker window | 7.03 years (F6: 8.0 target) | `metrics.json.years` |
| Cache start | 2019-05-31 (need 2018-06-12 for 8y) | `cache_prices/manifest.json` |
| Dominant open leak | `concentrated:structural_underinvestment_bull` (2021 + 2023) | IS attribution tags |
| Ledger overall trend | REGRESSING (T3+conc-hyst regressed vs baseline) | `latest_verdict.json` |
| Production_activation_allowed=false flags | 174 sites | grep |
| Closed autolearning chains | 2 of 7 (feature_gates + layer4_swap) | audit |
| Era-based selection | NOT in code (F1) | audit §1B |
| Crisis→action max delay | 1-30 trading days (F2) | audit §1C |

If any of these are stale or your fetch returns different numbers, **report the delta in your YAML** under `metadata.current_state_observed_vs_brief_delta` instead of silently overwriting.

### Your deliverable

**One file**: `docs/proposals/goals_20260615.yaml`

**Following the schema in `CODEX_GOAL_SETTING_BRIEF.md` §6.2 exactly.** Fill in:

1. **`metadata`** with TODAY's UTC timestamp and the 7 source checks you ran (include the commit SHA of the ledger row you read).
2. **`mission`** — copy verbatim from CLAUDE.md, mark `immutable: true`.
3. **`strategic_goals`** — **propose 2-3 goals** for **2026-Q3** (2026-07-01 to 2026-09-30) targeting the IS-CAGR gap, the 8y data shortfall, and the autolearning loop closure. Each MUST have probability_estimate + reasoning grounded in the F1-F6 findings.
4. **`tactical_goals`** — **propose 4-6 goals** for **the current week (2026-W24, ending 2026-06-21)**. Cover:
   - P0.1 bull-floor verdict + promotion decision (this week)
   - 8-year data bootstrap (this week or W25)
   - PR merge strategy between `claude/analyze-updated-code-OfEbu` and `codex/self-sustaining-loop-20260615` and `codex/github-agent-coordination-docs-20260615` (PR #63)
   - P1.3 data_readiness hard-fail lockdown (small, ship-able this week)
   - At least one parallel design-review task for ChatGPT Pro (P0.2 crisis wire OR P0.3 per-regime sub-model)
5. **`operational_goals`** — **at least 1 per tactical goal**, with `owner` field = `claude_code` | `chatgpt_pro` | `codex` | `dispatcher` | `user`.
6. **`risk_register`** — **at least 3 risks** with likelihood × impact × mitigation. MUST include:
   - 8y data bootstrap failure mode
   - Per-regime sub-model overfit risk
   - Merge-conflict risk between the 3 branches
7. **`anti_goals`** — explicitly commit to NOT pursuing these (the 10 prohibitions in BRIEF §9 minimum, plus any sprint-specific ones you identify).
8. **`acceptance_protocol`** — explicitly name who reviews each goal level (per BRIEF §5).

### Constraints (the BRIEF says these but they bear repeating here)

- ❌ **NEVER** propose a strategic goal with full-period CAGR as the PRIMARY KPI. Use IS-CAGR. Full CAGR allowed only as `reference_only` field. (F4)
- ❌ **NEVER** propose flipping `production_activation_allowed=true` outside the P1.2 gated process (BRIEF §0.2).
- ❌ **NEVER** propose a goal whose success can be claimed from a single A/B without IS-CAGR confirmation (BRIEF §4.2).
- ❌ **NEVER** propose a tactical goal without a `failure_criteria` and `fallback_on_failure`.
- ❌ **NEVER** propose a goal that requires master push without explicit user approval gate.
- ✅ **ALWAYS** anchor every KPI to a verifiable JSON path or file.
- ✅ **ALWAYS** include `probability_estimate` with reasoning for strategic goals (BRIEF §4.5).
- ✅ **ALWAYS** mark `dependencies` between goals (e.g., P0.3 depends on 8y data bootstrap).
- ✅ **ALWAYS** flag `baseline drift` risk if the commits compared have different universe modes or different `portfolio_policy` defaults (F5 lesson).

### Output protocol

1. Create branch `codex/goals-20260615` based on `codex/self-sustaining-loop-20260615` (HEAD `71f3198c` or newer).
2. Write `docs/proposals/goals_20260615.yaml` per BRIEF §6.2.
3. Commit message: `proposal(goals): 2026-Q3 strategic + W24 tactical targets`
4. PR title: `proposal(goals): Q3 2026 IS-CAGR closure + 8y data bootstrap + loop closure`
5. PR description must include:
   - **Source data SHAs** you fetched (ledger row sha, latest run id)
   - **Current state observed vs brief delta** (if any)
   - **Risk summary** (top 3 risks from your `risk_register`)
   - **Review request to ChatGPT Pro** with 1-paragraph emphasis on what you're least sure about
   - **User approval requested for**: the strategic_goals[] section (per BRIEF §0.1)
6. **Do NOT merge yourself.** Wait for ChatGPT Pro review + user approval.

### Anti-patterns observed in this project (do NOT repeat them)

| Anti-pattern | Where it happened | Lesson |
|---|---|---|
| Chasing full-period CAGR | T3+conc-hyst A/B looked like regression on full CAGR (-0.29pp) while really wash; ledger now uses IS-CAGR | Use IS-CAGR (F4) |
| Assuming baseline correct | "Cash overlay collapse" was misdiagnosed as nondeterminism for 5h; real cause was `portfolio_policy=production_baseline` footgun | Verify dispatch inputs match (F5) |
| Adding feature without registering | Phase 2 industry RS silently dropped for a week | Every new column → `PHASE_*_COLUMNS` + `keep_cols` |
| Treating sidecars as separate | Some "improvements" had no real impact because they don't reach broker_ledger_next_close | Trace every change to `broker_replay/<kind>/metrics.json` |
| Open-loop autolearning | 5/7 chains generate proposals but nothing auto-acts | Bias toward loop closure in your goals (BRIEF §3.3) |

### Required first paragraph of your response

Before producing the YAML, you MUST write a "verification preamble" in plain prose with:

1. **Date/time** you ran the 7 fetches.
2. **Each observed value** vs the table in this prompt — flag every delta.
3. **Did the bull-floor A/B (cd480423) land a new ledger row?** Yes/No with the commit SHA you saw. If No, that's a blocker — flag it before goals.
4. **What is `cloud_results/performance_ledger/latest_verdict.json` overall state?** IMPROVING / FLAT / REGRESSING / FIRST_RUN.
5. **Did the run land in `failed_runs/` or canonical?** Check `cloud_results/full_rebuild/<date>_global_alpha_universe/` vs `cloud_results/full_rebuild/failed_runs/`.
6. **Three-branch state**: list the HEAD SHA of `claude/analyze-updated-code-OfEbu`, `codex/self-sustaining-loop-20260615`, and `codex/github-agent-coordination-docs-20260615`. Are they on different bases?

Only after this preamble do you write the YAML.

### Final reminder

- Your YAML is a **proposal**, not an enacted decision.
- The strategic_goals section needs **user approval** before it counts.
- ChatGPT Pro will review and probably push back on probability estimates or risk omissions. **Welcome that feedback** — your job is to surface uncertainty honestly, not to defend numbers.

### Acknowledgment

End your response with:

> "I read CODEX_GOAL_SETTING_BRIEF.md (commit `<sha>`), SESSION_HANDOFF_20260615.md, SYSTEM_INTEGRATION_ANALYSIS_20260615.md, CLAUDE.md, ALPHAOPS_DATA_SYSTEM_CONTRACT.md, and the last ~500 lines of CHANGELOG.md. The YAML at `docs/proposals/goals_20260615.yaml` is on branch `codex/goals-20260615`, PR opened against `<base>`, awaiting ChatGPT Pro review and user approval on the strategic_goals section."

🟦 [END OF PROMPT — Codex starts working from here] 🟦

---

## 사용 방법 (메타-노트, Codex에 붙이지 마세요)

1. 위 `🟦 [PASTE TO CODEX FROM HERE] 🟦` 부터 `🟦 [END OF PROMPT — Codex starts working from here] 🟦` 까지 복사.
2. Codex 채팅/dispatch에 붙여넣기.
3. Codex가 verification preamble을 먼저 출력하는지 확인 — 이게 없으면 brief를 안 읽은 것.
4. YAML 출력 후 PR이 열리면 ChatGPT Pro 리뷰 요청.
5. ChatGPT Pro가 strategic goals의 확률 추정이나 위험 누락을 지적할 가능성이 큼 — Codex가 방어 모드로 가지 않도록, **2 rewrite round 후 3rd round는 사용자에게 직접 escalate** (BRIEF §6.2 acceptance_protocol).

## 만약 Codex가 prompt를 이해 못하면

- 가장 흔한 실패: §1 데이터 fetch를 안 함 → 추정값으로 YAML 채움.
  - 대응: "Re-read CODEX_GOAL_SETTING_BRIEF.md §1 — the 7 sources are MANDATORY"
- 두 번째: Mission 재정의 시도 (35/50 낮추기) → 즉시 reject.
- 세 번째: full CAGR을 primary KPI로 (F4 violation) → reject with "see BRIEF §3.1 + Finding F4"

---

**End of Codex Prompt File — 2026-06-15 10:35 KST**

Maintainer: Claude Code.
Update protocol: when Brief §1 source data paths change OR when new audit findings (F7+) emerge, regenerate this prompt.
