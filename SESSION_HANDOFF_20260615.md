# Session Handoff — 2026-06-15 KST

> **WHO AM I**: r1000 Quant Engine project (Russell 1000 + ADR + cycle plays, Top 30 institutional). Goal: AlphaOps broker-ledger production loop. Targets — Main CAGR ≥ 35% / MDD ≥ -25%, Concentrated CAGR ≥ 50% / MDD ≥ -25% (CLAUDE.md).
>
> **PURPOSE OF THIS FILE**: shortest possible "pick-up-where-we-left-off" brief for the **next session** to continue, with **explicit role split** between three agents (Claude Code in-CLI, ChatGPT Pro for strategy/review, Codex for parallel code work).
>
> **LIFETIME**: rewrite when next phase ships or when a new blocker appears. One active handoff only.

---

## 0. ACTIVE INBOX (2026-06-15 02:00 UTC)

**Branch**: `claude/analyze-updated-code-OfEbu` (NOT default branch — see §3 caveat for weekly cron).

**Current state** (HEAD = `3bd08c9b`):
- ✅ Self-sustaining evaluation loop is live: Tier-2 gates + IS attribution + performance ledger + bull-floor fix + weekly cron.
- 🟡 **A/B IN FLIGHT**: Full Rebuild `27516185696` on `cd480423` with `PHASE_REGIME_CAPACITY_BULL_FLOOR_ENABLED=1` + `portfolio_policy=alphaops_vnext_production`. Started 2026-06-14T23:58:08Z, ETA ~16:00-17:00 UTC.
- 📄 **Holistic audit committed**: `SYSTEM_INTEGRATION_ANALYSIS_20260615.md` (6 parallel Explore-agent passes, ~50 files). Read this first.
- 📊 **Ledger seeded with 2 historical rows** (`cloud_results/performance_ledger/ledger.jsonl`):
  - `27457206698` (a8b271ea, no T3): Main IS 22.14% / Conc IS 21.65%
  - `27498401423` (d42daf82, T3+conc-hyst, vNext): Main IS 21.45% / Conc IS 21.29%  → **REGRESSING**, next focus `concentrated:structural_underinvestment_bull`.

**This session's commits** (chronological):
1. `e19cce3c` Tier-2 strengthened gates (IS-CAGR / OOS-IS ratio / Sharpe / cash / recent-MDD)
2. `2691169e` IS attribution sidecar + 14pp leak diagnosis
3. `c68cef8e` performance ledger (cumulative self-evaluating memory)
4. `cd480423` two-way regime_capacity overlay (P0a bull-floor, env-gated default OFF)
5. `11f7a914` weekly cron heartbeat (Mon 09:00 UTC, dormant until merge to default)
6. `3bd08c9b` holistic system integration analysis (the audit doc)

---

## 1. CRITICAL CONTEXT — what is the engine actually doing today?

**Read first, in this order:**
1. **`SYSTEM_INTEGRATION_ANALYSIS_20260615.md`** (newest) — the full system map with file:line references. 6 surfaces analyzed: data collection, selection engine, crisis sidecar, autolearning, workflow orchestration, CAGR attribution chain.
2. **`CLAUDE.md`** — project basics, current baseline, contract.
3. **`docs/ALPHAOPS_DATA_SYSTEM_CONTRACT.md`** — do not skip; mandatory before changing selection/sizing/cash/broker-replay policy.
4. **`CHANGELOG.md`** last ~500 lines — recent decisions (last 5 entries are this session).
5. **`cloud_results/performance_ledger/ledger_summary.md`** — the cumulative verdict (read AFTER the A/B completes for the verdict; current state is REGRESSING from the 2 seed rows).
6. **This file** for the next-action plan and role split.

**Five honest findings from the audit (cite these in any agent reply):**

| # | Finding | Where verified |
|---|---|---|
| F1 | **"시대별 주도 종목 선정"은 코드에 없다.** Single global model; regime adjusts ensemble blend weights only, not coefficients. 2020 software ≠ 2024 AI but both score the same way. | `r1000_pipeline.py:9386-9505`, `r1000_candidate_lanes.py:18-87` |
| F2 | **Crisis → action 지연 1-30일.** Daily monitor is `research_only=True`. Real cash is decided once a month via `regime_state` (macro), not live crisis. | `tools/run_daily_crisis_monitor.py`, `tools/run_alphaops_vnext_policy_replay.py:2618-2800` |
| F3 | **Auto-learning은 5/7 open-loop.** 174 files set `production_activation_allowed=false`. Performance ledger is observability-only — no auto-action. | grep `production_activation_allowed`, `research/multi_agent_operating_plan_20260516/agent_contracts.md:8` |
| F4 | **Headline CAGR is OOS-inflated.** Main IS 21.45% / OOS 75.75% (3.53x). Conc IS 21.29% / OOS 129.36% (6.08x). The CLAUDE.md 35/50 baseline has the same shape — 50.75% Conc baseline is an OOS lottery on a ~22% IS engine. | `account_evaluation/official_metrics.json` windowed metrics, Tier-2 gates |
| F5 | **`portfolio_policy` default was a footgun.** `production_baseline` skipped the cash overlay → Main 19% / Conc 32% with cash 0.05%. I changed default to `alphaops_vnext_production` (commit `2479b839`). Documented as a CHANGELOG correction. | `.github/workflows/full_rebuild_manual.yml:95-104` |

---

## 2. NEXT STEPS — prioritized, with role split

The improvement plan has **3 priority tiers** and **11 concrete code-search steps** (see `SYSTEM_INTEGRATION_ANALYSIS_20260615.md` §4). This section names **who does what**.

### 2.1 Role Definitions

**Claude Code (in-CLI agent — "executor in the repo")**:
- Has direct repo access, can Read/Edit/Write/Bash/Grep.
- Owns: smoke tests, code edits, commits, GitHub workflow dispatches, sidecar wiring.
- **Always**: produce a smoke test for every new tool, register it in `tools/run_pr_validation.py`, run `tests/smoke_test.py --quick` before commit, push to `claude/analyze-updated-code-OfEbu`.
- **Never**: merge to default branch without explicit user OK; never force-push; never skip hooks (`--no-verify`); never delete `cloud_results/performance_ledger/ledger.jsonl`.

**ChatGPT Pro (strategy/review — "second pair of eyes")**:
- Best at: design review, math sanity checks, identifying bugs in proposed designs BEFORE Claude codes them, writing spec docs, comparing two competing architectures.
- Owns: design proposal review, statistical methodology audits (IS/OOS split sensitivity, IC decay, regime classifier stability), reviewing Claude's commits for blind spots.
- **Always**: ground critique in file:line references; if you flag a bug, propose the fix in pseudo-code.
- **Never**: write production Python directly (hand off to Claude/Codex); never claim "I implemented X" — only "I designed/reviewed X."

**Codex (parallel code worker — "extra hands")**:
- Best at: large refactors, mass test-writing, mechanical edits across many files, documentation cleanup.
- Owns: refactors that touch >10 files (e.g., `production_activation_allowed=false` mass review), mass smoke-test backfill, repetitive feature-store keep_cols audit, batch-file conversion.
- **Always**: open a separate branch (e.g., `codex/<task-name>`), submit a PR to `claude/analyze-updated-code-OfEbu` so Claude can review before merging.
- **Never**: ship to `claude/analyze-updated-code-OfEbu` without a PR; never change `cloud_results/performance_ledger/ledger.jsonl` directly.

**Coordination rule**: any task >= 4 hours of work or touching >= 5 files should go through ChatGPT Pro for design review first, then split between Claude (in-repo coding) and Codex (mechanical breadth) for execution.

### 2.2 P0 — currently shipping (this week)

#### P0.1 — Read bull-floor A/B verdict (Claude, ~30 min)

**Status**: A/B `27516185696` finishes ~16:00-17:00 UTC.

**Claude's checklist**:
```bash
# 1. Fetch latest
git fetch origin claude/analyze-updated-code-OfEbu
git pull --rebase origin claude/analyze-updated-code-OfEbu

# 2. Read the new ledger row (3rd entry)
cat cloud_results/performance_ledger/ledger_summary.md
# expected: 3 rows, the new one is run_id 27516185696 commit cd480423

# 3. Read IS attribution for the new run
cat cloud_results/full_rebuild/20260615_global_alpha_universe/is_attribution/concentrated_summary.md
# focus: did 2021 + 2023 stop being structural_underinvestment_bull?

# 4. Read Tier-2 gates
cat cloud_results/full_rebuild/20260615_global_alpha_universe/account_evaluation/official_metrics.json | jq '.portfolios | to_entries[] | {k:.key, cagr:.value.cagr, is_cagr:.value.is_cagr, max_dd:.value.max_dd, sharpe:.value.sharpe, strengthened_pass:.value.strengthened_pass}'
```

**Decision rule** (Claude executes; if uncertain, ask ChatGPT Pro for second opinion):
- **PASS** (= conc IS-CAGR > 23%, conc MDD ≥ -25%, Main not regressed): promote bull-floor to default ON. Edit `tools/run_alphaops_vnext_policy_replay.py:~2723` so `bull_floor_enabled = ...` defaults to `True` when no env override. Update smoke. New commit. New A/B with `PHASE_REGIME_CAPACITY_BULL_FLOOR_ENABLED=0` for the inverse confirmation.
- **FAIL** (conc IS-CAGR < 22% or MDD < -28% or Main regresses > 1pp): revert is unnecessary (default is OFF), but document the rejection in CHANGELOG with the numbers. Move to P0.2 directly.
- **PARTIAL** (IS-CAGR up but MDD worsens): ChatGPT Pro design review on whether to tune the floor (0.85 → 0.75) or restrict to `strong_bull` only.

#### P0.2 — Daily crisis → broker action wire (Claude + ChatGPT Pro design review, ~5-7 days)

**Why**: Audit Finding F2. Crisis signal exists but action arrives 1-30 days late because cash is decided once a month.

**ChatGPT Pro deliverable** (BEFORE Claude codes; ~2 hours):
- Read `tools/crisis_state_engine.py`, `tools/run_daily_crisis_monitor.py:179`, `tools/run_alphaops_vnext_policy_replay.py:2550-2700`, `tools/run_broker_ledger_replay.py`.
- Design a "crisis override row injector":
  - **Option A**: a sidecar that reads `daily_crisis_states.csv` and, on a GREEN→CRISIS_DEFENSE transition (within a calendar month), injects an override row in `operating_*_target_book.csv` dated at the transition date with cash weight = 0.35-0.50. broker_replay sees the new rebalance and fills T+1.
  - **Option B**: extend `apply_crisis_lane_policy` to accept a daily crisis state series and re-emit per-day target rows.
- Evaluate trade-offs (Option A is simpler / non-invasive; Option B is more correct but touches the main vNext code path).
- Pseudo-code the override row layout: which columns must match the existing book schema; which `selection_reason` value to use; how to avoid duplicating the rebalance trigger when next monthly rebalance is < 5 trading days away.
- **Hand-off doc**: write a 1-page design at `docs/proposals/crisis_override_injector.md` with file references and the chosen Option.

**Claude deliverable** (after design review):
- New `tools/run_crisis_override_injector.py` per the design.
- 8-test smoke at `tests/crisis_override_injector_smoke.py`. Cover: GREEN→CRISIS_DEFENSE transition injects row; back-to-back transitions don't double-inject; near-rebalance window suppresses injector; bear regime doesn't trigger (crisis already covered by monthly overlay); cash weight is exactly bounded; environment toggle `PHASE_CRISIS_OVERRIDE_INJECTOR_ENABLED` controls it; idempotent on re-run; respects existing CASH row schema.
- Wire into `tools/run_full_rebuild_sidecars.py` AFTER `run_alphaops_vnext_policy_replay` and BEFORE `run_broker_ledger_replay`.
- Default OFF for the first A/B. Dispatch A/B `PHASE_CRISIS_OVERRIDE_INJECTOR_ENABLED=1 + bull-floor (whatever P0.1 decided)`.

**Codex deliverable** (parallel, optional, ~1 day):
- Mass review of all `daily_crisis_monitor` callers + readers across the repo (`grep -r daily_crisis_monitor` and `crisis_action_status`) to ensure the new injector's outputs don't break a downstream consumer that assumes "advisory only."

#### P0.3 — Per-regime sub-model (Claude + ChatGPT Pro design + Codex parallel, ~2-3 weeks)

**Why**: Audit Finding F1. The IS-CAGR 21% ceiling on both books is a single-model ceiling. Per-regime training is the biggest lever.

**ChatGPT Pro deliverable** (1-2 days):
- Read `r1000_pipeline.py:9386-9505` (`compute_regime_ensemble_weights_adaptive`) + the walk-forward training loop (lines 9744-9832).
- Evaluate two design candidates:
  - **(a) Light — sample weights**: in the SAME ensemble, weight training samples by the regime they came from when the prediction target falls in regime R. Pro: minimal code change. Con: one set of coefficients per model still.
  - **(b) Heavy — per-regime sub-models**: train separate Ridge + CatBoost + LR per regime, choose at scoring time by current regime_state. Pro: real per-era leadership. Con: data sparsity in `deep_bear`/`strong_bull`; risk of overfitting per-regime; walk-forward becomes 5x heavier.
- Recommend ONE candidate with a numerical reason (e.g., COVID 2020 has X months bear, IS-period total has Y months — overfit risk for sub-models in deep_bear is …).
- **Spec doc**: `docs/proposals/per_regime_submodel.md` with:
  - Recommended design + alternatives
  - Module-level signatures (training function, scoring function, regime-routing)
  - Risks + mitigations (regime mis-classification → fallback to global model)
  - Smoke test outline
  - Expected runtime impact on FULL rebuild (extra h)
  - Acceptance criteria: IS-CAGR ≥ 25% (Main) / ≥ 30% (Conc) AND OOS/IS ratio ≤ 3.0x (no OOS-only lottery)

**Claude deliverable** (after design): implement the chosen design behind env toggle `PHASE_PER_REGIME_SUBMODEL_ENABLED`. ~500 LOC + smoke. Dispatch one A/B.

**Codex deliverable** (parallel):
- Refactor: move all PHASE_*_COLUMNS to a single registry (currently scattered in `r1000_config.py`) so the per-regime sub-model can declare which features it uses. ~6 files.
- Add the compile-time keep_cols guard (Finding §1F): assert all PHASE columns survive `build_feature_store.keep_cols`. ~2 files.

### 2.3 P1 — close the autolearning loop (next 1-2 weeks)

#### P1.1 — Ledger → auto-action router (Claude, ~3-5 days)

**Why**: Audit Finding F3. Ledger reports REGRESSING but nothing acts on it.

**Claude's plan**:
- New `tools/run_ledger_action_router.py`:
  - Read `cloud_results/performance_ledger/ledger.jsonl` last 3 rows.
  - If `state == REGRESSING` for 2 consecutive runs → auto-revert: read the last commit's CHANGELOG to find the `PHASE_*_ENABLED` flag that was promoted, flip it back off, open a PR (`mcp__github__create_pull_request`) targeting `claude/analyze-updated-code-OfEbu`.
  - If `state == IMPROVING` AND `strengthened_pass == true` for 2 consecutive runs → auto-promote: change the cfg-default of the relevant flag to True (open PR).
  - Idempotent (re-running on the same ledger row should not re-open the same PR).
- New workflow `.github/workflows/ledger_action_router.yml` triggered by `workflow_run: completed` of `full_rebuild_manual.yml`.
- 6-test smoke covering: REGRESSING streak triggers PR; IMPROVING streak triggers PR; FLAT does nothing; same-ledger re-run is idempotent; missing CHANGELOG flag pinpoint fails gracefully; PR title format matches convention.

**ChatGPT Pro review**: the auto-revert path is the highest-risk piece. Review for race conditions (what if the human pushed a manual fix between the regression and the next run?), and design the conflict-resolution policy.

#### P1.2 — `production_activation_allowed` auto-promotion gate (Codex + Claude review, ~1 week)

**Why**: Audit Finding F3. 174 files set this flag to false, blocking learned signals.

**Codex deliverable**:
- Audit all 174 occurrences. Categorize: (a) intentional research-only artifacts (most), (b) actually consumable by production but gated for safety, (c) dead code.
- Output: `docs/proposals/production_activation_audit.md` with the 3-bucket classification.

**Claude deliverable**:
- For category (b), wire a gate in `tools/auto_policy_promote.py:93+`: auto-flip `production_activation_allowed=true` if the source candidate's Tier-2 `strengthened_pass=true` AND IMPROVING streak ≥ 2 in the ledger.
- Smoke: gate fires only on the dual condition.

**ChatGPT Pro review**: classify which signals are safe to auto-activate (don't auto-activate anything that affects the broker_ledger_next_close gate without a human PR).

#### P1.3 — Data readiness lockdown (Claude, ~1-2 days)

**Why**: Audit Finding (workflow §5). `data_readiness_preflight.yml` and the in-rebuild `data_coverage_gate.py` are both warn-only.

**Claude's plan**:
- Read `SESSION_HANDOFF.md` (the OLD 2026-06-09 version) §"data-hole program" for the lockdown floors that were promised but never enforced.
- In `.github/workflows/full_rebuild_manual.yml:531-535`, remove `--no-fail` and `--warn-only` for the proven layers (per `docs/DATA_COVERAGE_GATE_LOCKDOWN.md` if it exists; else propose the floors: `coverage_etf_ratio >= 0.30`, `coverage_top_manager_ratio >= 0.05`, SEC companyfacts age ≤ 5 days).
- Add a separate Tier-2 set still in warn-mode for emerging layers.
- The lockdown must NOT block the bot's weekly cron from running — instead it should route the failing run to `failed_runs/<run_id>/` (already wired at line 895-920) AND open an issue (`mcp__github__issue_write`) tagging the feed at fault.

### 2.4 P2 — diagnostic + infra (next 2-4 weeks, parallelizable)

| Task | Lead | Cost | Purpose |
|---|---|---|---|
| Per-name CAGR/MDD attribution tool (`tools/run_per_position_cagr_attribution.py`) | Claude | 3-5 d | Decompose +Npp gains: "NVDA +2.3pp / 2021 cash deploy +2.9pp / cost drag -0.6pp" |
| MDD trough → holdings snapshot (extend `broker_replay/metrics.json`) | Claude | 1-2 d | Auto-answer "which positions drove the 2023-08-17 trough?" |
| Move `cost_bps`, `max_fill_lag_days`, `oos_start` to `r1000_config.py` | Codex | 0.5 d | Configurability for sensitivity A/B |
| `keep_cols` compile-time guard in `build_feature_store` | Codex | 0.5 d | Prevent Phase 2-style silent drops |
| ADR + cycle plays auto-candidate scanner (`tools/run_universe_candidate_scanner.py`) | Claude | 1 wk | Quarterly yfinance scan → PR proposes additions/removals |
| Sub-daily/PRWV selective trailing-stop A/B | Claude | 1 wk | Selective stops by conviction (vs. T4 reactive's wash) |
| `outputs/` core artifacts → git-committed | Codex | 0.5 d | cross-run analysis without archive hunting |
| Macro release-calendar awareness | ChatGPT Pro design + Claude | 1 d | M2/CPI real-release-date-aware lag |

### 2.5 P3 — long-term (>1 month)

- True era-based selection (per-regime candidate filtering + sector rotation by regime). Requires P0.3 (per-regime sub-model) as prerequisite. ChatGPT Pro should design the rotation-table specification.
- Live paper trading bridge (`live_trading_safety_audit.py` already exists but is research-only). Requires P1.1 + P1.2 + P1.3 first.

---

## 3. 주의사항 — DO and DON'T

### 3.1 Hard rules (NEVER violate)

| Rule | Why |
|---|---|
| ❌ NEVER skip git hooks (`--no-verify`, `--no-gpg-sign`). | The hooks enforce smoke tests and CHANGELOG format. |
| ❌ NEVER push to default branch (`master`/`main`) without explicit user OK. | Default-branch pushes can trigger the new weekly cron unexpectedly. Stay on `claude/analyze-updated-code-OfEbu`. |
| ❌ NEVER delete `cloud_results/performance_ledger/ledger.jsonl` or any rows in it. | It's the only longitudinal memory. Removing rows breaks the trend analysis. |
| ❌ NEVER claim a CAGR/MDD as production-valid unless `outputs/data_readiness/summary.json`, `outputs/reports/dataset_coverage_audit.json`, `outputs/sec_enriched_candidate_replay/summary.json`, `outputs/alphaops_vnext/summary.json`, AND `outputs/portfolio_system_guard/error_check.json` all support the run. | Per CLAUDE.md L7-9 (the AlphaOps data-first contract). |
| ❌ NEVER interpret full-period CAGR as the engine's quality. | Audit Finding F4. Use Tier-2 IS-CAGR + OOS/IS ratio. The ledger trends IS-CAGR for this reason. |
| ❌ NEVER trust an A/B result from a run that didn't use `portfolio_policy=alphaops_vnext_production` (or the new default). | Audit Finding F5. Without vNext, the cash overlay is bypassed and the result is broken-baseline only. |
| ❌ NEVER set `production_activation_allowed: true` in any artifact without P1.2 gate (or explicit user OK). | Audit Finding F3. The 174 flags exist by design for safety. |
| ❌ NEVER add a new PHASE_X_COLUMN signal without adding it to BOTH `r1000_config.py PHASE*_COLUMNS` AND `build_feature_store.keep_cols`. | The silent-drop trap (Audit Finding §1F). Use the smoke test as a guard. |
| ❌ NEVER write `cloud_results/performance_ledger/ledger.jsonl` from any tool other than `tools/run_performance_ledger.py`. | Schema versioning. |

### 3.2 Soft conventions (follow unless you have a clear reason not to)

| Convention | Rationale |
|---|---|
| Default new env-gated features OFF; promote via A/B + ledger evidence. | Risk control + reproducible A/B math. |
| Every new tool gets a smoke (`tests/<name>_smoke.py`) + register in `tools/run_pr_validation.py`. | Catches ~80% of bugs in seconds vs hours of GHA. |
| CHANGELOG entry per ship — English only, `HH:MM KST` timestamp, list symbols_added/changed. | CLAUDE.md L168-174. |
| Use the natural snake_case for env-gates (`PHASE_T3_LEADER_HYSTERESIS_ENABLED`, not `PHASE_PHASE_T3_...`). | Accept both via `phase_is_enabled` but document the natural form. The double-PHASE footgun cost us a day. |
| When dispatching an A/B, ALWAYS include `portfolio_policy=alphaops_vnext_production` explicitly until P1.3 lockdown makes it impossible to omit. | F5 footgun. |
| Run `tests/smoke_test.py --quick` before every commit and `tools/run_pr_validation.py --quiet` before every push. | The ~10s investment catches the 2h-cycle GHA bugs. |
| When proposing a design, ALWAYS include a Bayes-style sanity check: "If this feature has no real effect, what would the ledger row look like?" — i.e. specify the null hypothesis. | Avoids motivated reasoning. |

### 3.3 Recovery procedures

**"The A/B finished but the ledger still shows REGRESSING for the bull-floor"**:
1. Check `cloud_results/full_rebuild/20260615_global_alpha_universe/account_evaluation/official_metrics.json` directly.
2. Verify `regime_capacity_bull_floor_lifted` count > 0 in `outputs/alphaops_vnext/regime_capacity_overlay_audit.csv` (was the toggle actually applied?).
3. If toggle was applied but IS-CAGR didn't move: the leak is elsewhere (selection IC, not sizing). Move to P0.3 sooner.
4. If toggle was NOT applied: env-var passing through the workflow is broken; check `.github/workflows/full_rebuild_manual.yml:465-470` (phase_env_overrides parsing).

**"The ledger disagrees with the broker_replay metrics"**:
1. Run `tools/run_performance_ledger.py --latest-run cloud_results/full_rebuild/<date>_global_alpha_universe --ledger-dir /tmp/test --run-id check --commit check` locally to reproduce.
2. The ledger reads `account_evaluation/official_metrics.json` and `is_attribution/summary.json` — if those are stale, regenerate them.
3. NEVER hand-edit the ledger; regenerate by re-running `run_performance_ledger.py` with the same `run-id` (it dedups).

**"A FULL rebuild fails on cache eviction"**:
- This is a known issue. Re-dispatch with the same inputs; GHA cache TTL is 7 days.
- DO NOT switch to QUICK_RESCORE mode for a verdict — QUICK_RESCORE bypasses the feature_store rebuild and doesn't reflect new PHASE columns.

**"`portfolio_system_guard/error_check.json` has `hard_error_count > 0`"**:
1. Run is demoted to `cloud_results/full_rebuild/failed_runs/<run_id>/`. Workflow status is still success (this is by design — see Audit Finding workflow §6).
2. Read `outputs/portfolio_system_guard/error_check.json` to see the specific hard errors.
3. Common hard errors: negative cash, invalid target weights (sum > 1.05), missing required columns.
4. DO NOT route through the failed_runs directory's metrics as production evidence.

---

## 4. BOOTSTRAP PROMPT — copy-paste for any new chat

If you're starting from zero in any of Claude, ChatGPT Pro, or Codex:

```
I am taking over the r1000-quant-engine project, branch claude/analyze-updated-code-OfEbu, HEAD 3bd08c9b.

Repository: github.com/wscha231/r1000-quant-engine (private).
Target: AlphaOps broker-ledger production loop. Main CAGR >= 35% / MDD >= -25%, Conc CAGR >= 50% / MDD >= -25%.

Read these in order before doing anything:
1. SESSION_HANDOFF.md (THIS file) — for role split, next-action priorities, and DO/DON'T rules
2. SYSTEM_INTEGRATION_ANALYSIS_20260615.md — the holistic system audit (6 surfaces)
3. CLAUDE.md — project basics, current baseline, contract
4. docs/ALPHAOPS_DATA_SYSTEM_CONTRACT.md — selection/sizing/cash/broker-replay policy contract
5. CHANGELOG.md last ~500 lines — most recent decisions
6. cloud_results/performance_ledger/ledger_summary.md — cumulative IS-CAGR trajectory
7. `git log --oneline -10 origin/claude/analyze-updated-code-OfEbu` — expected HEAD 3bd08c9b or newer

My role is: [Claude Code / ChatGPT Pro / Codex] (pick one — see §2.1 of SESSION_HANDOFF for the role split).

The current active priority is: [P0.1 verdict reading / P0.2 crisis wire / P0.3 per-regime sub-model / P1.x / P2.x] (pick from §2 of SESSION_HANDOFF based on what's already in flight; if A/B `27516185696` has just completed, P0.1 is the right entry point).

Before any code change, confirm Finding F5 (portfolio_policy default) is unchanged and Finding F4 (use IS-CAGR not full-period CAGR) is respected.

If you find any DRIFT between what SESSION_HANDOFF claims and what the repo actually shows (e.g., ledger row count, recent commits, A/B verdict), say so explicitly before acting. Don't paper over discrepancies.
```

---

## 5. OPEN QUESTIONS — for the next session to consider

1. **Is the bull-floor floor (conc 0.85, main 0.90) too aggressive?** If P0.1 shows MDD worse, ChatGPT Pro should redesign with regime-tiered floors (`bull=0.80`, `strong_bull=0.85`, `exceptional_bull=0.90`).
2. **Should the daily-crisis injector also handle exit transitions** (CRISIS_DEFENSE → GREEN re-deployment)? Symmetric injection avoids the "stuck in cash" trap.
3. **Per-regime sub-model**: is there enough `deep_bear` data (only COVID + 2022 in 7y window) to train without overfitting? ChatGPT Pro to evaluate.
4. **Auto-promotion gate**: should the IMPROVING streak required for auto-promotion be 2 or 3? 3 is safer but 2 lets us iterate faster. Trade-off worth quantifying.
5. **Era-based selection (P3)**: how do we represent "era" — discrete regime labels, or a continuous embedding learned from feature panels? Major architectural choice.

---

## 6. WHAT NOT TO DO (anti-patterns observed this session)

| Anti-pattern | What happened | Lesson |
|---|---|---|
| Chase full-period CAGR | T3+conc-hyst A/B looked like a regression (-0.29pp Conc full CAGR) when really it was a wash on the production-baseline arm. Ledger now uses IS-CAGR. | Use Tier-2, not headline. |
| Assume the A/B baseline is correct | "Cash overlay collapse" entry blamed nondeterminism for 5 hours before tracing it to the `portfolio_policy=production_baseline` default footgun. | Verify the dispatch inputs MATCH the baseline before interpreting deltas. |
| Build a feature without claiming it in `PHASE_*_COLUMNS` | Phase 2 industry RS was silently dropped for a week (CLAUDE.md L118-130). | Every new column → registry + smoke. |
| Treat sidecars as separate problems | Until this session's audit, no one had mapped which sidecars actually touch broker_ledger_next_close vs. which are research-only. Result: many "improvements" had no real impact. | Always trace a proposed change to `broker_replay/<kind>/metrics.json`. If you can't, it's research, not production. |

---

**End of SESSION_HANDOFF — written 2026-06-15 02:09 UTC, valid until next phase ships or A/B verdict completes (whichever first).**
