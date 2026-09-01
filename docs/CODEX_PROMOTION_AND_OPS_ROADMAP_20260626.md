# Codex Roadmap — Promotion Path + Auto-Management Ops (2026-06-26)

> Handoff: Codex. Author: Claude Code (web). Scope: how to get from the current
> research baseline to a PROMOTABLE system and then to MAINTAINED / auto-managed
> operation. Companions: `docs/CODEX_MEASUREMENT_PROTOCOL.md`,
> `docs/CODEX_WORK_ORDER_CAGR_MDD_LEVERS.md`, `docs/CODEX_RESEARCH_LEADER_CAPTURE.md`,
> `CLAUDE.md`. Still research-only; nothing here authorizes production or live trading.

---

## 0. Honest status & what "promotion-ready" means

Clean 7Y baseline (run `28074476465`, broker_ledger_next_close):
Main `33.15% / -26.02%`, Concentrated `46.24% / -25.82%`. **Both sleeves miss both
targets.** The 7Y window gate now PASSES (`years 7.055`) — data gate #1 is solved.
The remaining non-performance evidence/substrate blocker is
**`pit_universe_label_clean=false`**. Performance acceptance is still a separate blocker
because both sleeves miss the current target contract.

Promotion requires TWO things, not one:
1. **`pit_universe_label_clean=true`** — the standing non-performance evidence/substrate
   blocker (Track A).
2. At least one sleeve clears its acceptance bar on broker-ledger, valid window, **with OOS**
   (Track C alpha) — OR the bar is re-defined to an achievable production gate (§2).

Do not conflate "a lever passed a screen" with "promotable." Promotion is gated by the
**Production Acceptance Contract** (§2), not by any single CAGR number.

---

## 1. TRACK A (CRITICAL PATH) — PIT-clean universe label

This is the #1 promotion blocker and has been deferred while alpha work proceeded. It is a
data-integrity task, independent of alpha. **Do not flip the flag — earn it.**

How the flag is read (do not change the consumer): `tools/run_account_evaluation.py::
pit_universe_label_clean()` returns true iff any of `pit_universe_label_clean`,
`pit_universe_clean`, `historical_universe_pit_clean`, `official_pit_r1000` is truthy in
`broker_metrics` / `readiness` / `universe_health`. Today none are set, so the gate emits
`pit_universe_label_missing`.

Work order:
1. **Locate the producer**: where historical universe membership is built
   (`r1000_data_collector.py` candidate-universe build + `historical_membership_file`;
   the `universe_health` artifact). Determine whether membership is **as-known-at-date** or
   backfilled with today's constituents (survivorship/look-ahead).
2. **Establish a PIT-clean membership source**: date → constituents that were actually
   index members at-or-before that date, each with `available_from ≤ rebalance_date`. No
   future additions/deletions leaked into past dates.
3. **Validate (the evidence that earns the flag)**: for every rebalance date, assert the
   universe used contains only PIT-valid members; emit a coverage + no-future-membership
   audit (counts, any violations). This audit is the proof.
4. **Emit the flag only on a clean audit**: write `historical_universe_pit_clean=true`
   (or `official_pit_r1000=true`) into `universe_health` / readiness **only when** the audit
   has zero look-ahead violations and adequate coverage. Never hardcode true.
5. **Re-run** account_evaluation → confirm `pit_universe_label_clean=true` and
   `production_promotion_allowed` unblocks (with the other gates).

Integrity rule: same discipline as the window-tolerance and no-op guards — the flag must
be a machine-emitted consequence of a passing audit, never a manual toggle.

---

## 2. Production Acceptance Contract (define BEFORE promoting)

A run is PROMOTABLE only if ALL hold (write this as `PRODUCTION_ACCEPTANCE_CONTRACT.md` +
a checker that reads the artifacts):
- `pit_universe_label_clean = true` (Track A).
- Metric mode `broker_ledger_next_close`; window gate `valid_7y` (machine-readable).
- **OOS holds**: the last ~2y OOS fold shows the same direction as IS (no IS-only result).
- Walk-forward stability + `future_labels_excluded=true`, `used_forward_return_in_ranking=false`,
  OOS lock green, leakage 0.
- `data_freshness_contract` green; `portfolio_system_guard` hard-errors = 0.
- Risk-adjusted floors, not just CAGR: e.g. IR ≥ threshold, Sharpe ≥ threshold,
  `excess_cagr > 0`, MDD ≤ −25%.
- **Live/paper parity**: broker-ledger replay reconciles with a paper-execution ledger over
  ≥ N months before any live step.

**Target-bar decision (raise with the user; do not change silently):** `Conc 50% absolute CAGR` over a clean PIT 7Y
is very aggressive (broad levers all failed; 46.24/−25.82 looks near the achievable frontier).
Consider defining the PRODUCTION bar on **relative + risk** terms (e.g. `excess_cagr ≥ +12pp
vs SPX AND IR ≥ 1.0 AND MDD ≤ −25%`) rather than an absolute 50% that may be unreachable
without overfitting. This is a governance choice — surface it; do not silently lower a bar.

---

## 3. Auto-Management / Ops Plan (runtime, after promotion)

Substantial scaffolding already exists (`daily_crisis_monitor`, `decision_cadence`,
`review_dispatcher`, `self_correction_queue`, `auto_learning`, `account_evaluation`,
`live_trading_safety`, `live_trading_risk_controls`). Write `AUTO_MANAGEMENT_OPS_PLAN.md`
that wires them into one loop:

**Operating loop**
- Daily: data refresh → `data_freshness_contract` → `daily_crisis_monitor` (regime) →
  (on change) target book → paper/broker execution → `account_evaluation` → guard/drift
  checks → alerts.
- Weekly: watchlist refresh, new-leader detection.
- Monthly: full rebalance + walk-forward re-validation.

**Monitoring & alerts**: data staleness / coverage drop, guard hard-errors, **live-vs-backtest
performance drift**, regime transitions, MDD approaching limit, turnover anomaly.

**Self-correction discipline (non-negotiable):** auto-learning may **detect, alert, and roll
back** — it must **never auto-ship a policy change**. Every policy mutation requires
`applied_count>0` + broker-ledger A/B + OOS + the acceptance contract + **human approval**.
Automation owns observation and safety; humans own shipping.

**Periodic re-validation**: scheduled walk-forward re-run; re-confirm pit-clean + window +
gates; detect performance decay early.

**Safety**: `live_trading_safety` + risk controls, position/turnover caps, hard stops,
kill-switch, **paper-first** (N months paper parity before any live capital). 2022-style
defensive cash behavior is sacred and must survive every change.

---

## 4. Alpha next — measure what's coded; avoid the audit treadmill

Measurement infra is now sufficient. The risk is building more diagnostics without shipping
a validated win. **Decision checkpoint: measure the already-coded levers before building more.**
- **Priority: measure A1 SHAKEOUT (PR #161) + A2 earnings gate** — they target the largest
  measured inefficiency (premature sells +8.4% 126d, `pct_held_365d_plus=0%`) and help BOTH
  sleeves. `applied>0` → broker A/B. Likely higher impact than the rescue candidate.
- **Concentrated dropped-leader rescue** (work order already merged) — measure with the
  segment-REQUIRED + fixed IS(2019-06-03→2024-06-02)/OOS(2024-06-03→end) discipline.
- **Structural directions (not broad layers)**: (a) winner hold-duration extension
  (`pct_held_365d` 0→positive) is the single highest-leverage change; (b) Concentrated
  **sizing** (score_power concentration — the mechanism that produced 33% in the champion
  grid) as an A/B; (c) Main MDD via **regime/market-heat proactive de-risk**, measured strictly.
- Each lever: env-gated default OFF, `applied>0`, broker-ledger accept, OOS, capture non-regress.

---

## 5. Sequencing & decision checkpoints

1. **Start two parallel tracks now**: Track A (pit-clean — promotion critical path) and
   Track C alpha (measure A1/A2 + rescue candidate).
2. **Checkpoint after A1/A2 + rescue measured**: if a sleeve clears its bar (or the re-defined
   production bar) on broker-ledger + OOS → write the acceptance contract checker. If none →
   re-scope the target (§2) or pivot to structural levers (hold-duration / sizing). Do NOT
   build more audits.
3. **Promotion** only when Track A done AND a sleeve passes the acceptance contract.
4. **Then** stand up the auto-management loop, paper-first.

---

## 6. Guardrails (unchanged)
PIT-only; env-gated default OFF; broker_ledger_next_close for acceptance; no production
promotion until pit-clean + contract; no live trading until paper parity; automation never
auto-ships policy; 2022 defensive cash sacred; no answer-sheet / forward-blind design + OOS;
no proxy 8Y/10Y. Earn every flag from a passing audit — never toggle one.
