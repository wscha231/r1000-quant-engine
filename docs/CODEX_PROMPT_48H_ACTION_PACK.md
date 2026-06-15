# Codex Prompt — Next 48h Action Pack (with Location Discipline)

> 이 문서는 **Codex에 그대로 붙여넣는 prompt**입니다.
> 핵심 규칙: **모든 작업이 "Local cwd" vs "GitHub remote" 중 어디서 일어나는지 명시**.
> Codex와 Claude Code 둘 다 이 규칙을 지킵니다 — 누가 어디서 무엇을 만지는지 항상 추적 가능.
> 출처 brief: `docs/CODEX_GOAL_SETTING_BRIEF.md`, `docs/CODEX_PROMPT_NEXT_GOALS.md`.

---

## 🟦 [PASTE TO CODEX FROM HERE] 🟦

Codex, you are the parallel-breadth + safety-loop agent on r1000-quant-engine. The user has reviewed your goals proposal (PR #65) and the Claude verdict, and we now have **48-hour concrete action pack** for you. Follow the location discipline rules below STRICTLY.

---

## 0. Location Discipline — ALWAYS state where you are working

Every action in this pack happens in EXACTLY ONE of three locations. Before every command, you state which one in a tag.

### Three locations

| Tag | What it means | Examples |
|---|---|---|
| **`[LOCAL]`** | Your local clone working tree. Files only exist after `git pull`. Commits exist only after you `git push`. | `cd /path/to/r1000-quant-engine && git checkout <branch>`, `python3 tools/foo.py`, `pytest tests/bar.py`, `git add … && git commit …` |
| **`[GITHUB]`** | The remote `github.com/wscha231/r1000-quant-engine`. Source of truth for branches/PRs/CI. Use `gh` CLI or MCP github tools. | `gh pr view 65`, `gh pr merge 63`, `gh workflow run full_rebuild_manual.yml`, reading `cloud_results/.../ledger.jsonl` via the GitHub web UI or `gh api` |
| **`[DRIVE]`** | Google Drive mirror (`H:/codex/...` on user's Windows machine, or the Drive mount). Long-term run artifacts that may not be in GitHub. | `H:/codex/tmp_r1000_coord_pr/...`, full rebuild artifacts from `cloud_results/full_rebuild/<date>/` mirrored from GitHub |

### Rules

1. **Every command** in your response is prefixed with one of `[LOCAL]`, `[GITHUB]`, or `[DRIVE]`. No exceptions.
2. **When you switch location**, write a one-line transition note: `# transition: [LOCAL] → [GITHUB] because the PR diff is the truth, not my local working tree`.
3. **When you read state**, state which location you're reading from and why. Example: `# reading ledger.jsonl from [GITHUB] (origin/codex/self-sustaining-loop-20260615) because that is the canonical version, not my local clone which may be stale.`
4. **When two locations might disagree**, you MUST resolve which is source of truth before acting. Example: "Local says X but `gh` says Y. Truth is [GITHUB] for `origin/<branch>` state, so I use Y."
5. **Never assume local == remote.** Always `git fetch origin` before reading branch state, and state when you did the last fetch.
6. **Never commit directly from `[DRIVE]`.** Drive is read-only for the agent — for any change, copy file to `[LOCAL]`, commit, push to `[GITHUB]`.

### Source of truth matrix

| Question | Where the truth is |
|---|---|
| What does branch X currently contain? | `[GITHUB]` `origin/X` (after `git fetch origin`) |
| What runs are in flight? | `[GITHUB]` via `gh run list` or MCP `actions_list` |
| What does the bull-floor A/B (`27516185696`) say? | `[GITHUB]` `origin/claude/analyze-updated-code-OfEbu:cloud_results/performance_ledger/ledger.jsonl` row for that run_id |
| What does the goals YAML currently propose? | `[GITHUB]` `origin/codex/goals-2026-06-15:docs/proposals/goals_20260615.yaml` |
| Is the master branch ready for PR #64 merge? | `[GITHUB]` PR #64 conclusion status |
| What did this Claude session ship? | `[GITHUB]` `origin/claude/analyze-updated-code-OfEbu` log (commits e19cce3c..7ab29e9d) |
| Smoke test pass/fail at HEAD? | `[LOCAL]` after `git pull` AND `[GITHUB]` PR Validation workflow |
| Run artifacts older than 365 days? | `[DRIVE]` only |

---

## 1. Repository coordinates (verify by `git fetch origin` first)

- **Repo**: `https://github.com/wscha231/r1000-quant-engine` (private)
- **Default branch**: `master` — commit `02aa686b` as of 2026-06-15 11:00 UTC (verify yourself)
- **3 active branches** based on `master`:
  - `codex/self-sustaining-loop-20260615` — HEAD `27215532` (your work + ledger + IS attribution + bull-floor port already in)
  - `codex/goals-2026-06-15` — HEAD `ae637668` (PR #65 base on the line above)
  - `codex/github-agent-coordination-docs-20260615` — HEAD `a0d081e9` (PR #63 docs)
- **1 archive branch (DO NOT merge whole)**:
  - `claude/analyze-updated-code-OfEbu` — HEAD `7ab29e9d`, based on OLD master `93b623a5`. Contains Claude's original research commits. Codex already re-implemented the executable parts on a clean master base, so this branch is **research source + docs only**, never whole-merge.

### Verify with [LOCAL]:
```bash
[LOCAL] cd /path/to/your/clone
[LOCAL] git fetch origin
[LOCAL] for b in master codex/self-sustaining-loop-20260615 codex/goals-2026-06-15 codex/github-agent-coordination-docs-20260615 claude/analyze-updated-code-OfEbu; do
[LOCAL]   echo "  $b -> $(git rev-parse --short origin/$b)"
[LOCAL] done
# Expected output should match the SHAs above; if different, report the delta.
```

---

## 2. Verified facts (Claude session confirmed by direct git inspection)

| Fact | Value | Verified from |
|---|---|---|
| **Bull-floor A/B verdict (run `27516185696`, commit `cd480423`)** | **LANDED + PASSED** | `[GITHUB]` `origin/claude/analyze-updated-code-OfEbu:cloud_results/performance_ledger/ledger.jsonl` row 3 |
| Main IS-CAGR (bull-floor row) | **22.90%** (was 21.45% on `27498401423`, +1.45pp) | same ledger.jsonl |
| Main full CAGR (bull-floor row) | **35.20%** (Tier-1 35% target PASS) | same |
| Main MDD (bull-floor row) | **-24.49%** (was -25.93%, +1.44pp improvement, Tier-1 PASS) | same |
| Conc IS-CAGR (bull-floor row) | **22.41%** (was 21.29%, +1.12pp) | same |
| Conc full CAGR (bull-floor row) | **44.43%** (Tier-1 50% target -5.57pp gap) | same |
| Conc MDD (bull-floor row) | **-25.92%** (Tier-1 -25% target -0.92pp) | same |
| `master` HEAD | `02aa686b` | `git rev-parse origin/master` |
| `master` has `tools/run_performance_ledger.py`? | **NO** | `git cat-file -e origin/master:tools/run_performance_ledger.py` returns failure |
| `master` has bull-floor code? | **NO** (0 hits for `bull_floor` in vnext) | grep |
| `codex/self-sustaining-loop-20260615` has ledger + bull-floor + IS attribution? | **YES** (codex re-implemented on clean master base) | git cat-file checks |
| Codex `run_performance_ledger.py` vs Claude version | **DIFFERENT** (re-implemented, not cherry-picked) | `diff` between branches |
| codex/sustaining ledger.jsonl rows | **2 (seed only)** — bull-floor verdict row NOT YET in codex ledger | `wc -l` |

**Critical implication**: bull-floor verdict (row 3, run `27516185696`) lives ONLY on `claude/analyze-updated-code-OfEbu`. If PR #64 merges to master without porting that row, **we lose the bull-floor data point**. See §4 Action 2.

---

## 3. What this Claude session shipped on `claude/analyze-updated-code-OfEbu` (research source only — DO NOT whole-merge)

Commits to reference but not whole-merge:

| SHA | Content | Port status |
|---|---|---|
| `e19cce3c` | Tier-2 strengthened gates | **Already re-implemented in codex/sustaining** (verified: 9 strengthened_pass hits) |
| `2691169e` | IS attribution sidecar | **Already in codex/sustaining** |
| `c68cef8e` | Performance ledger | **Re-implemented in codex/sustaining BUT DIFFERENT schema** — reconcile required (§4 Action 1) |
| `cd480423` | P0a bull-floor overlay | **Already in codex/sustaining** (19 hits for capped_proportional_fill / bull_floor) |
| `11f7a914` | Weekly cron + portfolio_policy default fix | **Check codex/sustaining** for `cron: '0 9 * * 1'` in `full_rebuild_manual.yml` |
| `3bd08c9b` | SYSTEM_INTEGRATION_ANALYSIS_20260615.md | **Doc only** — cherry-pick OK after master merge (but verify line:column refs still match) |
| `c6aca6c9` | CODEX_GOAL_SETTING_BRIEF.md | **Doc only** — check if codex/sustaining has it |
| `7ab29e9d` | CODEX_PROMPT_NEXT_GOALS.md | **Doc only** — same as above |

### Verify with [GITHUB]:
```bash
[GITHUB] gh api repos/wscha231/r1000-quant-engine/contents/docs/CODEX_GOAL_SETTING_BRIEF.md?ref=codex/self-sustaining-loop-20260615 --jq '.path' 2>&1 | head -1
# If "Not Found" → codex/sustaining is missing this doc, port required
```

---

## 4. The 48-hour action pack

Each action has a **location tag**, **owner** (`codex` or `claude_code` or `user`), **time slot**, and **success criteria**. Codex executes the `owner: codex` ones.

### Action 1 — **Reconcile two ledger implementations** (T+0~2h) `[LOCAL + GITHUB]`

**Owner**: codex.

**Why**: Claude and codex re-implemented `tools/run_performance_ledger.py` separately. Schema may differ. If both write to the same `cloud_results/performance_ledger/ledger.jsonl` (after PR #64 merges to master and Claude branch port happens), the JSONL becomes inconsistent.

**Steps**:
```bash
# 1. Fetch both versions to local for inspection
[LOCAL] git fetch origin
[LOCAL] git show origin/claude/analyze-updated-code-OfEbu:tools/run_performance_ledger.py > /tmp/ledger_claude.py
[LOCAL] git show origin/codex/self-sustaining-loop-20260615:tools/run_performance_ledger.py > /tmp/ledger_codex.py
[LOCAL] diff /tmp/ledger_claude.py /tmp/ledger_codex.py | head -100

# 2. Compare JSONL schemas:
#    (a) field names in output row
#    (b) order of fields
#    (c) values for is_cagr (which window — IS-period from account_evaluation, or computed locally?)
#    (d) trend classification (REGRESSING band — Claude uses 0.5pp, what does codex use?)

# 3. Decision rule: codex/sustaining version is canonical (clean master base, already in PR #64).
#    BUT: if Claude version has fields codex doesn't, document them as `future` extension fields.

# 4. Output: write a 1-paragraph reconciliation note to:
[LOCAL] # docs/proposals/ledger_reconciliation_20260615.md
# State: "codex/sustaining version is canonical. Claude-version fields {X, Y, Z} not yet adopted, may be added in PR #66 if needed."
```

**Then [LOCAL] → [GITHUB] transition**:
```bash
[LOCAL] git checkout -b codex/ledger-reconciliation-20260615 origin/codex/self-sustaining-loop-20260615
[LOCAL] # add docs/proposals/ledger_reconciliation_20260615.md
[LOCAL] git add docs/proposals/ledger_reconciliation_20260615.md
[LOCAL] git commit -m "docs: reconcile two performance_ledger implementations"
[LOCAL] git push -u origin codex/ledger-reconciliation-20260615
[GITHUB] gh pr create --base codex/self-sustaining-loop-20260615 --head codex/ledger-reconciliation-20260615 \
  --title "docs: ledger reconciliation" \
  --body "Documents canonical version. No code change. See ledger_reconciliation_20260615.md."
```

**Success criteria**: PR opened, ChatGPT Pro can review the reconciliation note in <30 min. No code merged yet.

---

### Action 2 — **Port bull-floor verdict row to codex ledger** (T+2~4h) `[LOCAL + GITHUB]`

**Owner**: codex.

**Why**: Bull-floor A/B verdict (`27516185696`, commit `cd480423`) row exists ONLY on `claude/analyze-updated-code-OfEbu` ledger. If PR #64 merges to master without this row, the verdict data point is lost. Next official run on master will regenerate it ONLY IF bull-floor flag is preserved.

**Steps**:
```bash
# 1. Extract the bull-floor row from [GITHUB]
[LOCAL] git show origin/claude/analyze-updated-code-OfEbu:cloud_results/performance_ledger/ledger.jsonl | tail -1 > /tmp/bull_floor_row.jsonl
[LOCAL] cat /tmp/bull_floor_row.jsonl | python3 -c "import sys, json; r=json.load(sys.stdin); assert r['run_id']=='27516185696', r['run_id']; print('OK', r['commit'])"

# 2. Validate schema against codex canonical version (from Action 1)
[LOCAL] python3 -c "
import json
with open('/tmp/bull_floor_row.jsonl') as f: claude_row = json.load(f)
# load codex's ledger row as schema template
import subprocess
codex_text = subprocess.run(['git','show','origin/codex/self-sustaining-loop-20260615:cloud_results/performance_ledger/ledger.jsonl'], capture_output=True, text=True).stdout
codex_row = json.loads(codex_text.splitlines()[0])
claude_fields = set(claude_row.keys())
codex_fields = set(codex_row.keys())
print('only-claude:', claude_fields - codex_fields)
print('only-codex:',  codex_fields - claude_fields)
print('common:', len(claude_fields & codex_fields))
"

# 3. Translate Claude row to codex schema (drop unknown fields, add missing required fields)
#    Output a single-line JSONL file: /tmp/bull_floor_row_codex_schema.jsonl

# 4. Append to codex ledger on a new branch
[LOCAL] git checkout -b codex/port-bull-floor-row origin/codex/self-sustaining-loop-20260615
[LOCAL] cat /tmp/bull_floor_row_codex_schema.jsonl >> cloud_results/performance_ledger/ledger.jsonl
[LOCAL] # verify 3 rows now
[LOCAL] wc -l cloud_results/performance_ledger/ledger.jsonl  # expect 3

# 5. Run codex's ledger script in --dry-run / --verify mode to confirm reads cleanly
[LOCAL] python3 tools/run_performance_ledger.py --verify-only cloud_results/performance_ledger/ledger.jsonl

# 6. Commit + push + PR
[LOCAL] git add cloud_results/performance_ledger/ledger.jsonl
[LOCAL] git commit -m "data: port bull-floor verdict row (run 27516185696, cd480423) to codex ledger

Verdict: Main IS 21.45→22.90% (+1.45pp), Main MDD -25.93→-24.49% (+1.44pp).
Conc IS 21.29→22.41% (+1.12pp), Conc MDD -25.88→-25.92% (-0.04pp wash).
Main now PASSES Tier-1 (35.20%/-24.49%). Conc still gaps -5.57pp on CAGR.

Source: origin/claude/analyze-updated-code-OfEbu:cloud_results/performance_ledger/
ledger.jsonl row 3. Schema-translated to codex canonical version.

Without this port, PR #64 merge would lose the only direct bull-floor measurement."
[LOCAL] git push -u origin codex/port-bull-floor-row
[GITHUB] gh pr create --base codex/self-sustaining-loop-20260615 --head codex/port-bull-floor-row \
  --title "data: port bull-floor verdict row (run 27516185696) to codex ledger" \
  --body "Preserves bull-floor A/B measurement before PR #64 merges to master. Single JSONL line append. See commit body for verdict."
```

**Success criteria**: codex/sustaining ledger has 3 rows after this PR merges. Bull-floor +1.12pp Conc / +1.44pp Main MDD signal preserved.

---

### Action 3 — **Promote bull-floor to default ON** (T+4~6h) `[LOCAL + GITHUB]`

**Owner**: codex.

**Why**: Bull-floor A/B verdict is verified PASS (Conc IS +1.12pp, Main MDD +1.44pp, Main Tier-1 pass). Default should flip OFF → ON.

**Steps**:
```bash
# 1. Find the toggle in codex/sustaining
[LOCAL] git checkout -b codex/promote-bull-floor origin/codex/port-bull-floor-row  # builds on Action 2
[LOCAL] grep -n "phase_is_enabled.*regime_capacity_bull_floor\|phase_is_enabled.*bull_floor\|bull_floor_enabled\s*=" tools/run_alphaops_vnext_policy_replay.py
# Find the line setting bull_floor_enabled default to False, flip to True

# 2. Edit: change `bull_floor_enabled = bool(phase_is_enabled(... default=False) ...)` → `default=True`
#    But: ALSO add a `phase_is_enabled("regime_capacity_bull_floor_disabled", default=False)` escape hatch
#    so a user can FORCE OFF for a control A/B without code change.

# 3. Update smoke (tests/bull_floor_overlay_smoke.py) — the "off by default" test now needs the
#    DISABLED env, not the absence of ENABLED env.

# 4. Verify smoke passes locally
[LOCAL] python3 tests/bull_floor_overlay_smoke.py
[LOCAL] python3 tests/smoke_test.py --quick

# 5. Commit + push + PR
[LOCAL] git commit -am "feat(P0a): promote bull-floor to default ON

Bull-floor A/B (run 27516185696) verdict:
  Main IS-CAGR 21.45% -> 22.90% (+1.45pp)
  Main full CAGR 34.33% -> 35.20% (Tier-1 PASS)
  Main MDD -25.93% -> -24.49% (+1.44pp improvement)
  Conc IS-CAGR 21.29% -> 22.41% (+1.12pp)
  Conc MDD -25.88% -> -25.92% (-0.04pp, wash)
  Conc full CAGR 44.57% -> 44.43% (-0.14pp, within noise)

Net: small but clean win, especially on Main MDD. Default OFF -> ON.
New escape hatch PHASE_REGIME_CAPACITY_BULL_FLOOR_DISABLED for control A/B."
[LOCAL] git push -u origin codex/promote-bull-floor
[GITHUB] gh pr create --base codex/self-sustaining-loop-20260615 --head codex/promote-bull-floor \
  --title "feat(P0a): promote bull-floor to default ON (verdict PASS)" \
  --body "See commit body for A/B numbers. Replaces ENABLE env with DISABLE env so default is ON."
```

**Success criteria**: bull-floor PR opens with smoke tests updated, verdict numbers cited. ChatGPT Pro reviews; if MDD wash concern raised, Codex provides per-month attribution from is_attribution.

---

### Action 4 — **Update goals YAML with bull-floor verdict + honest probability** (T+6~10h) `[LOCAL + GITHUB]`

**Owner**: codex.

**Why**: `docs/proposals/goals_20260615.yaml` `current_state` shows seed values (21.45/21.29) — stale. Need bull-floor verdict values (22.90/22.41) AND probability 0.50 → 0.33 per Claude verdict.

**Steps**:
```bash
[LOCAL] git checkout -b codex/goals-update-bull-floor origin/codex/goals-2026-06-15
[LOCAL] # Edit docs/proposals/goals_20260615.yaml:
#   - metadata.current_state.main_is_cagr: 0.2145 → 0.2290
#   - metadata.current_state.conc_is_cagr: 0.2129 → 0.2241
#   - metadata.current_state.main_full_cagr: ... 0.3520
#   - metadata.current_state.main_mdd: -0.2449
#   - metadata.current_state.conc_full_cagr: 0.4443
#   - metadata.current_state.conc_mdd: -0.2592
#   - metadata.current_state.ledger_row_count: 3
#   - Add metadata.bull_floor_verdict: pass
#   - Add metadata.bull_floor_evidence_run_id: "27516185696"
#   - strategic_goals[0].probability_estimate: 0.50 → 0.33
#   - strategic_goals[0].probability_reasoning: |
#       Verified by bull-floor A/B (run 27516185696):
#       single structural fix lifted Main IS +1.45pp / Conc IS +1.12pp.
#       To reach SG-2026Q3-01 targets (Main 28%, Conc 32%), we need
#       5-8 more such fixes accumulated, of which most fail or wash
#       (T3, T4, conc-hysteresis A/B history). The only single lever
#       large enough to bridge the gap (+5.10pp Main / +9.59pp Conc to
#       targets) is era-aware sub-model (P0.3), and its E1 IC-analysis
#       gate has not been run. 8y bootstrap is evidence-only (~+0.5pp).
#       Honest estimate 0.33 reflects this — was 0.50 (Codex initial).
#   - mission.honest_baseline_caveat (new field): |
#       Bull-floor A/B confirmed: single fix ceiling ~1pp. CLAUDE.md
#       targets (35/50/-25/-25) likely require either (a) era-aware
#       sub-model breakthrough, or (b) acceptance that current OOS-
#       inflated headlines are the true ceiling and revising the
#       contract. USER has NOT yet authorized contract revision —
#       mission stays at 35/50.
#   - mission.target_conflict_flag (new field): "30/-25, 50/-28 relaxations mentioned in some planning docs are NOT user-ratified; proposal keeps 35/50."

[LOCAL] python3 -c "import yaml; yaml.safe_load(open('docs/proposals/goals_20260615.yaml'))"  # validate
[LOCAL] git add docs/proposals/goals_20260615.yaml
[LOCAL] git commit -m "docs(goals): update with bull-floor verdict + honest probability re-estimate

current_state reflects ledger row 3 (run 27516185696):
  Main IS 22.90% (was 21.45%), full 35.20%, MDD -24.49%
  Conc IS 22.41% (was 21.29%), full 44.43%, MDD -25.92%

SG-2026Q3-01 probability 0.50 -> 0.33 with explicit reasoning citing
bull-floor +1pp ceiling. Adds mission.honest_baseline_caveat noting
single-fix ceiling and that targets likely require era-aware sub-model
breakthrough OR contract revision (latter not user-ratified)."
[LOCAL] git push -u origin codex/goals-update-bull-floor
[GITHUB] gh pr create --base codex/goals-2026-06-15 --head codex/goals-update-bull-floor \
  --title "docs(goals): update with bull-floor verdict + honest probability" \
  --body "Reflects verified A/B numbers and honest re-estimate per Claude verdict."
```

**Success criteria**: PR #65 stack now has accurate current_state. ChatGPT Pro re-reviews strategic_goals with new probability.

---

### Action 5 — **Self-correction router: duplicate suppression + status column** (T+10~24h) `[LOCAL + GITHUB]`

**Owner**: codex.

**Why**: Q6 P0 — without duplicate suppression and status tracking, router queues redundant A/B and can't tell `queued` from `measured` from `rejected`.

**Steps**:
```bash
[LOCAL] git checkout -b codex/router-status-column origin/codex/self-sustaining-loop-20260615
[LOCAL] # Find router queue file
[LOCAL] grep -rn "router_queue.json\|workflow_dispatch_payloads.json" tools/ | head

# Add to router payload schema:
#   - status: "queued" | "dispatched" | "measured" | "rejected" | "ready_for_human_review"
#   - dispatched_at_utc, measured_at_utc, rejected_at_utc (nullable)
#   - dispatch_run_id (nullable)
#   - measured_ledger_run_id (nullable)
#   - payload_hash (sha256 of normalized payload for duplicate detection)
#   - ledger_sha_at_queue (for staleness detection)

# Duplicate suppression logic:
#   - On enqueue: compute hash, if exists in queue with status in {queued, dispatched}, skip + log
#   - On dispatch: stamp dispatched_at_utc + dispatch_run_id, status -> dispatched
#   - On run completion (via workflow_run trigger): match dispatch_run_id, status -> measured
#   - If ledger trend on measured row is IMPROVING + strengthened_pass, status -> ready_for_human_review
#   - Else status -> rejected

# Stale payload detection:
#   - On dispatch: compare current ledger HEAD SHA vs ledger_sha_at_queue
#   - If different, log warning, optionally re-evaluate

[LOCAL] # Implement + write smoke
[LOCAL] python3 tests/self_correction_router_smoke.py  # extend existing
[LOCAL] python3 tests/smoke_test.py --quick
[LOCAL] git add ...
[LOCAL] git commit -m "feat(router): duplicate suppression + status column + stale payload detection

Q6 P0 closure (per Claude verdict). Without these, router queues redundant
A/B and cannot distinguish queued/dispatched/measured/rejected."
[LOCAL] git push -u origin codex/router-status-column
[GITHUB] gh pr create --base codex/self-sustaining-loop-20260615 --head codex/router-status-column ...
```

**Success criteria**: router queue carries `status`, duplicate enqueue is blocked, smoke test covers all 5 states.

---

### Action 6 — **Wait on user actions for merges** (T+24~48h) `[GITHUB]` (Codex monitors)

**Owner**: user, ChatGPT Pro, Claude Code (NOT codex — codex does not merge).

These are NOT codex actions. Codex monitors and reports.

| Sub-action | Owner | When |
|---|---|---|
| Review + merge PR #63 (docs cross-agent) → master | user | T+6~24h |
| Review + merge PR #64 (self-sustaining-loop) → master | user + ChatGPT Pro | T+24~36h, after PRs from Actions 1+2+3+5 are stacked into it |
| Review + merge PR #65 (goals) after Action 4 stacked | user + ChatGPT Pro | T+36~48h |
| Dispatch continuation-winner A/B if Conc gap still ≥5pp | user via gh CLI | T+48h+ |

Codex reports:
```bash
[GITHUB] gh pr list --repo wscha231/r1000-quant-engine --state open --base master
[GITHUB] gh pr list --repo wscha231/r1000-quant-engine --state open --base codex/self-sustaining-loop-20260615
[GITHUB] gh run list --workflow=full_rebuild_manual.yml --limit 5
```

---

## 5. Required output format for Codex

### 5.1 Verification preamble (BEFORE any action)

```
Verification preamble — 2026-06-15 HH:MM UTC

Location confirmation:
  [LOCAL]  clone path: <path>
  [LOCAL]  last `git fetch origin`: <timestamp>
  [GITHUB] api access: <gh auth status>
  [DRIVE]  N/A for this session (or specify mount)

Branch SHAs observed (after fetch):
  origin/master = <sha>  (expected 02aa686b)
  origin/codex/self-sustaining-loop-20260615 = <sha>  (expected 27215532)
  origin/codex/goals-2026-06-15 = <sha>  (expected ae637668)
  origin/claude/analyze-updated-code-OfEbu = <sha>  (expected 7ab29e9d)

  Deltas from prompt: <none / list>

Bull-floor verdict row (run 27516185696):
  [GITHUB] origin/claude/analyze-updated-code-OfEbu ledger.jsonl: PRESENT / ABSENT
  [GITHUB] origin/codex/self-sustaining-loop-20260615 ledger.jsonl: PRESENT (3 rows) / ABSENT (2 rows)

Plan: I will execute Actions 1, 2, 3, 4, 5 in this order. Each PR opens against
<base>. I will NOT merge any PR. I will pause before Action 5 to confirm Actions 1-4
PRs were reviewed.
```

### 5.2 During execution — per command

Every `bash` command starts with the location tag:
```bash
[LOCAL] cd /home/user/r1000-quant-engine
[LOCAL] git fetch origin
[LOCAL] git checkout -b codex/foo origin/codex/self-sustaining-loop-20260615
[LOCAL] # ... edits ...
[LOCAL] git commit -m "..."
[LOCAL] git push -u origin codex/foo
# transition: [LOCAL] → [GITHUB] because PR creation is a remote-side action
[GITHUB] gh pr create --base codex/self-sustaining-loop-20260615 --head codex/foo ...
[GITHUB] gh pr view <num> --json url --jq .url
# transition: [GITHUB] → [LOCAL] to start next action
[LOCAL] git checkout -b codex/bar origin/codex/foo
```

### 5.3 After each action — short status

```
Action N complete:
  Branch:  codex/<name>
  Commits: <count> (sha range <first>..<last>)
  PR:      <url>
  Location: [GITHUB] (all changes pushed)
  Local working tree: clean / dirty (state)
  Next action: M
```

### 5.4 Acknowledgment at end

```
I read CODEX_GOAL_SETTING_BRIEF.md, this prompt file (Next 48h Action Pack),
SESSION_HANDOFF_20260615.md, and verified all 3 branch SHAs at [GITHUB] via
`gh api`. The 5 PRs opened by my actions are:
  Action 1: <url>  (ledger reconciliation note)
  Action 2: <url>  (port bull-floor row)
  Action 3: <url>  (promote bull-floor default ON)
  Action 4: <url>  (update goals YAML)
  Action 5: <url>  (router status column)

All changes pushed to [GITHUB]. Local working tree clean.
Awaiting ChatGPT Pro review on Actions 3+4 (probability estimate + MDD wash
concern) and user merge decisions on Actions 1-5.
```

---

## 6. Anti-patterns Codex MUST avoid

| Anti-pattern | Symptom | Correct behavior |
|---|---|---|
| Ambiguous location | "I edited ledger.jsonl" without saying [LOCAL] or [GITHUB] | Always tag location |
| Stale `origin` reading | Reading branch state without `git fetch origin` first | Always fetch before reading |
| Whole-merging Claude branch | `git merge origin/claude/analyze-updated-code-OfEbu` | NEVER. Only cherry-pick the bull-floor row (Action 2) and docs if missing |
| Self-merging PR | `gh pr merge` on own PR | NEVER. Open PR, wait for human |
| Skipping verification preamble | Jumping into bash commands | Always start with §5.1 |
| Modifying ledger.jsonl without tool | `vim cloud_results/.../ledger.jsonl` | Only `tools/run_performance_ledger.py` writes ledger. Action 2 appends via script |
| Cherry-pick from Claude branch's full commit | `git cherry-pick c68cef8e` (Claude's ledger commit) | Skip — codex already re-implemented. Only port the DATA row (Action 2) |
| Updating master directly | Any push to `origin/master` | Only the user merges to master |
| Mixing actions across branches | One commit touching files for Action 1 + Action 3 | Each action = own branch + own PR |

---

## 7. Escalation triggers

Stop and notify user/ChatGPT Pro if:

- Action 1 reveals codex ledger and Claude ledger schemas are **incompatible** (e.g., field types differ).
- Action 2 row port fails JSON validation (likely schema mismatch).
- Action 3 promote breaks Tier-2 smoke (bull-floor on by default causes any other test to fail).
- Bull-floor MDD wash on Conc (-0.04pp) becomes a concern after re-running attribution.
- Any branch SHA differs from prompt by more than one commit.
- ChatGPT Pro rejects Action 4's probability re-estimate.
- User requests goals YAML re-write before Action 4 PR opens.

---

## 8. Acknowledgment template (end your response with this)

```
I read docs/CODEX_GOAL_SETTING_BRIEF.md, docs/CODEX_PROMPT_NEXT_GOALS.md,
this prompt (Next 48h Action Pack), and verified branch SHAs at [GITHUB].
I will execute Actions 1-5 in order, each on its own branch with its own PR.
I will NOT merge any PR. All file mutations happen in [LOCAL], all branch/PR
state is [GITHUB] source-of-truth. I will report after each action.

PRs to expect:
  Action 1: codex/ledger-reconciliation-20260615 → codex/self-sustaining-loop-20260615
  Action 2: codex/port-bull-floor-row → codex/self-sustaining-loop-20260615
  Action 3: codex/promote-bull-floor → codex/self-sustaining-loop-20260615
  Action 4: codex/goals-update-bull-floor → codex/goals-2026-06-15
  Action 5: codex/router-status-column → codex/self-sustaining-loop-20260615

Starting Action 1 now.
```

🟦 [END OF PROMPT — Codex starts here] 🟦

---

## 사용 방법 (메타-노트, Codex에 붙이지 마세요)

1. 🟦 [PASTE TO CODEX FROM HERE] 🟦 ~ 🟦 [END OF PROMPT — Codex starts here] 🟦 사이 복사.
2. Codex에 붙여넣기.
3. **Codex의 첫 응답이 §5.1 verification preamble로 시작하는지** 확인. 안 그러면 prompt 안 읽은 것 — "Re-read §0 location discipline + §5.1 preamble template" 응답.
4. **모든 bash 명령에 [LOCAL] / [GITHUB] / [DRIVE] tag가 붙는지** 확인. 안 붙으면 reject.
5. 각 PR이 열릴 때 URL 확인.
6. **Action 6 (user/ChatGPT Pro 영역)을 Codex가 침범하지 않는지** 확인.

## Claude Code도 같은 규칙 따른다 (이 prompt와 일관)

Claude Code가 코드 작업할 때도:
- 모든 명령에 `[LOCAL]` / `[GITHUB]` / `[DRIVE]` tag 명시.
- `git fetch origin` 전에 branch SHA 가정 금지.
- Claude 브랜치(`origin/claude/analyze-updated-code-OfEbu`)는 **research/docs source 전용**, 코드 머지 source 아님.
- `master` 직접 push 금지 — user만.

---

**End of Codex 48h Action Pack — 2026-06-15 12:25 UTC**

Author: Claude Code.
Update protocol: regenerate when bull-floor verdict updates, branch SHAs shift more than 3 commits, or PR #64 merges to master.
