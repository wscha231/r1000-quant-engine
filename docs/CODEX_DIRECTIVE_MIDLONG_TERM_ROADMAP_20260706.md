# Codex Directive — Mid/Long-Term Roadmap (Post-Run287)

> Author: Claude Code (web reviewer), 2026-07-06. Successor to
> `CODEX_DIRECTIVE_POST_RUN287_REINFORCEMENT_20260706.md` (R1–R5, now
> implemented in PR #218). This is the **multi-phase plan**, not a single work
> order. It sequences the structural unblocks that actually gate future
> CAGR/MDD and eventual service — the tactical alpha search is exhausted and is
> not the path.

## 0. Where we are — why the plan changes shape

Everything measurable on the current run287 generated book is settled:

- Cash-carry does **not** close the gap: Main 33.81% / −25.36%, Conc 48.41% / −22.96% (both fail).
- ~60–70% of the frozen→generated drop was the honest 2026-07-02 window, not hook failure.
- Main MDD is **structural** (2021-11→2022-09 bear); exit-timing is **not** a lever (0 material latency); cluster-cap is **rejected** (cut CAGR ~8pp for ~0.7pp MDD).
- Concentrated cap/replacement with rank/RS/revenue is **exhausted** (+0.01pp); the missed alpha needs a **new decision-time source** (W4), which is **absent** in the worktree.
- The local regen substrate is **not runner-parity** (492/981 cache missing, ~37% book weight divergence). W1 determinism is proven **locally only** — determinism ≠ runner fidelity.
- Both headline numbers are **survivorship-inflated** (`pit_universe_label_clean=false`); the dominant inflation component (delisted exclusion) is **unmeasured**.

**Conclusion:** the binding constraints are **substrate + data**, not signals. Adding indicators is forbidden and futile. The plan has three converging tracks:

- **Track A — Substrate integrity** (cache parity → determinism+fidelity → pit-clean membership). Unlocks trustworthy measurement and the only route off the production blocker.
- **Track B — Alpha source expansion** (W4 PIT earnings/guidance / Form4 / 13F). The only non-exhausted alpha path; Concentrated-first.
- **Track C — Sustainment/ops** (monitoring, alarms, champion/challenger, review SLA — from `SUSTAINMENT_OPERATING_BLUEPRINT_20260703.md`). What makes returns survivable and enables a service.

### Gate chain (endgame)

```
cache parity  →  determinism + runner-fidelity baseline  →  pit-clean membership
      →  survivorship-honest baseline  →  trustworthy alarms
      →  restricted-beta service (3 monthly cycles)  →  public (6–12mo ledger + compliance)
```

No stage may be skipped. A number is production-valid only after **pit-clean + determinism-verified**; everything before that is research/proxy.

## Non-negotiables (persist across all phases)

No new fullrun until a candidate clears its gate on a **parity** substrate AND the user approves one run. No production promotion / live trading / public performance wording while `pit_universe_label_clean=false`. No falsified-lever revival (bull-floor/gross-floor, broad hold/exit-delay, cap-safe per-name sizing, crash/VIX/DD predictors, tighter stops, revision-proxy). Forward returns are audit labels only. No hindsight editing of losing months/tickers, no end-date cherry-picking, no threshold re-pick after seeing losses. WIP ≤ 2 in flight. Every experiment ends in a committed verdict; rejects are assets. Cost ladder never skipped: cheap screen → fixed-book replay A/B → one fullrun only for a gate-passing candidate.

---

## Phase 0 — Close the run287 loop + parity foundation  *(now, ~1 week)*

**Objective.** Merge PR #218 clean; establish a runner-parity local substrate so every later measurement is trustworthy.

**Work items.**
1. PR #218 pre-merge (from the review): V1 R5 caveat hard-block (forensics summary carries `runner_parity_status`+survivorship caveats; smoke asserts value ≠ `missing` and blocks acceptance labels on `parity_documented_gap`); V2 XNYS helper wired into `verify_alphaops_fullrun_readiness.audit_age_days` AND `run_latest_price_date_audit.stale_trading_days_between` (not just defined); F1 W1 "determinism ≠ runner fidelity" note; F2 R2 `0.0pp` reframed (dominant component unmeasured); F3 R3 "MDD-benefit under-powered" note. → un-draft & merge.
2. **R1 full resolution** — restore the local price cache to the runner's **981 tickers** (`tools/run287_parity_cache_restore.py`; source: runner `target_generation_input_manifest.json` + existing free providers, no new paid data). Re-run the W1 double-run and the metric sidecar on the **981-cache** substrate.

**Acceptance.** `runner_parity_status=parity_exact` (0/0/0 date/ticker mismatch, `max_weight_delta_abs ≤ 1e-9` local-vs-runner), OR a fully quantified residual gap with per-ticker `missing_bars.csv` and its measured CAGR/MDD impact. `run287_w1_determinism_exact` gains `runner_fidelity_status ∈ {established, residual_documented}`.

**Exit gate.** A local substrate that is both deterministic AND runner-faithful. Until this passes, **no regeneration-based attribution or hook test is trusted** (this is why Phase 1 depends on it).

**Anti-leakage.** No ticker dropped to force a match; every excluded bar listed. No end-date change. No target-book regeneration for scoring.

---

## Phase 1 — Substrate-honest baseline + Main structural verdict  *(~1–2 weeks)*

**Objective.** Re-establish the single reference baseline on the parity substrate, and reach an honest verdict on whether Main −25% is reachable with any non-falsified lever.

**Work items.**
1. Re-run the official + cash-carry sidecar on the parity substrate; publish the **parity baseline** (replaces the 498-cache proxy numbers as the reference).
2. **Main MDD final test** — on the parity substrate (where the −25.36 drawdown actually reproduces), test the remaining *legitimate* diversification levers as fixed-book/regenerated counterfactuals: (a) correlated-cluster exposure cap re-tested where MDD can actually move (proxy was under-powered), (b) entry-time factor/duration balance. JOINT gate: MDD inside −25 in ≥2 eras AND CAGR ≥35, both accounting modes. If none pass → record **Main −25.36 as an honest structural failure** on this universe.
3. Upgrade R2 survivorship toward a two-sided bound if any free membership-churn signal exists; otherwise keep the one-sided proxy and state the deflated gap range explicitly.

**Acceptance.** A parity-substrate baseline JSON with the full contract fields; a Main verdict labelled `main_mdd_lever_found` (→ Phase-3-style candidate) or `main_mdd_structural_unreachable_on_current_universe`.

**Exit gate.** The team knows the true (parity, survivorship-framed) deficit and whether Main is a signal problem or a **universe/data** problem. If structural, Main's only remaining lever is pit-clean membership (Phase 2) — not alpha.

---

## Phase 2 — PIT-clean membership  *(~3–5 weeks; the production meta-blocker)*

**Objective.** Remove `pit_universe_label_clean=false` — the single documented production blocker — and de-inflate every number.

**Work items.**
1. **Free proxy build** — historical R1000 membership PIT file the engine already consumes (`load_historical_universe_membership` / `apply_historical_membership_filter`): schema `["ticker","Name","sector","cik10","date_from","date_to"]`. Sources: archived IWB holdings snapshots over time, any free constituent-history feed. Label `proxy`; state the survivorship ceiling honestly (fallback to current IWB stays biased).
2. **Delisted-name price restoration** — extend the cache to include names that left the index mid-window (kills early-year survivorship on the price side).
3. **Paid-data decision packet** — scope CRSP / Russell reconstitution (the one purchase with proven ROI per the blueprint): cost, coverage, exactly which blockers it clears, ROI vs the free proxy ceiling. **Surface to user for buy/stay decision.**

**Acceptance.** `check_10y_backtest_readiness` (or the pit gate) shows `pit_universe_label` as the *only* remaining hard blocker collapsed to `proxy_accepted`, OR a clean paid membership file if purchased. A re-measured baseline with the survivorship delta quantified (proxy-run vs current-constituents-run).

**Exit gate.** Either a pit-clean (paid) universe → production path opens, or a documented proxy + an explicit user decision on the paid feed. **No production promotion until pit-clean is genuinely true, not proxy.**

**Anti-leakage.** Membership admitted only by `available_from` / first-bar dates known at each rebalance date. No forward membership, no delisted backfill invented from current constituents.

---

## Phase 3 — W4 alpha source (Concentrated path)  *(~4–6 weeks; parallel with Phase 2)*

**Objective.** Open the only non-exhausted alpha lane — a decision-time source stronger than rank/RS/revenue — and, if it screens positive, ship one Concentrated hook honestly.

**Work items (strict order — do not skip a rung).**
1. **Source acquisition** — build a PIT feed with dated rows and `available_from ≤ decision_date`: EDGAR-derived EPS/guidance, Form4 insider, or 13F (CUSIP→ticker build). Emit `research_ready=true` only with coverage-eligible provenance.
2. **OOS source screen BEFORE any hook** — does the source carry ex-ante IC on the Concentrated `cap_or_replacement` miss set, out-of-sample? If IC ≈ 0 → negative evidence, stop; if free-derived version is insufficient → paid-feed decision to user.
3. **One hook, ex-ante only** — if the screen passes, design a single Concentrated hook from the source; predeclare thresholds; test hook-off/hook-on on the **parity** generated book, zero-yield AND cash-carry, multi-era.
4. **Ship gate** — ΔCAGR ≥ +1.59pp (the measured Conc deficit) without breaching −25% MDD, OOS/IS not worse, applied-count no-op proof, cross-book (fixed + regenerated).

**Acceptance.** Either a screened-positive source + a gate-passing Conc candidate (→ eligible for one approved fullrun), or negative evidence that the free-derived W4 feed is insufficient (→ paid-feed decision).

**Anti-leakage.** Forward returns never enter ranking. No losing-month/ticker restoration. The source screen's forward-label result must be re-validated OOS by the ex-ante rule (the candidate-1 lesson: screen said +9.26%, ex-ante rule delivered +0.01pp — the goodness must be *capturable*, not just *present*).

---

## Phase 4 — Sustainment / ops layer  *(~6–12 weeks; after substrate is trustworthy)*

**Objective.** Build the monitoring + fallback + self-improvement layer (blueprint S1–S5) so returns survive regime change and the system can eventually be a service. Backend-only (Telegram/push deferred until deployment).

**Work items.**
1. **Forward health ledger + alarm evaluator** (`run_alphaops_alarm_evaluator.py`, `update_forward_service_ledger.py`): daily rows — rolling 12m excess vs SPY-TR, DD-budget consumption, pick hit-rate, cluster HHI, signal→action lag, turnover/cash drift, freshness, post-parity book-hash match. Alarm ladder 0–3 (de-risk by **allocation only**, never ad-hoc picking).
2. **Weekly cron empty-input fix** (service-critical): schedule events default inputs correctly; missing input → `blocked_missing_input`, never a crash.
3. **Review SLA**: every EXIT_REVIEW/WARNING + alarm ≥1 human-resolved within 2 trading days; unresolved → committed `outputs/alerts/UNRESOLVED_*.md`; lag recorded (fixes the June-signal/July-crash gap).
4. **Champion/challenger quarterly harness** on existing `auto_learning` scaffolding, gated by the ship gate; retrain on the pit-clean/parity window; promote only if challenger beats champion; never hot-swap.
5. **CI baseline lock**: parity baseline metrics asserted in smoke; any PR moving them without a verdict doc fails CI.

**Acceptance.** Alarms fire on fixture shocks; cron survives empty inputs; ledger append-only with hashes; challenger harness produces a verdict, not a narrative.

**Exit gate.** Trustworthy, exception-driven monitoring on a pit-clean/parity substrate → the precondition for any service claim.

---

## Phase 5 — Service readiness  *(long-term, months 3–12)*

**Objective.** Move from research to a restricted, then public, service — only on the honest gate chain.

**Sequence.** determinism + pit-clean baseline → 3 monthly live-shadow cycles with the alarm ladder proving out → restricted-beta (defined users, simulated-data contract labels on every number) → public at 6–12 months of clean ledger + compliance review. Fallback asset published *before* any drawdown = benchmark + T-bill (worst case degrade to SPY + cash-carry, an honest floor).

**Non-negotiable.** Every public number carries the data-contract labels; no forward-return-derived claim; current holdings are process outputs, never a forward promise.

---

## Sequencing, WIP, and decision points

**Critical path:** Phase 0 (parity) → Phase 1 (honest baseline + Main verdict) → Phase 2 (pit-clean) → Phase 4 (sustainment) → Phase 5 (service). **Phase 3 (W4 alpha) runs in parallel** with Phase 2 once Phase 0 lands. WIP ≤ 2 (one substrate item + one alpha/ops item).

**User decision points (surface, do not decide unilaterally):**
- **D1 (Phase 2):** buy CRSP/Russell PIT membership, or stay on the free proxy (accepting the survivorship ceiling and no production promotion)?
- **D2 (Phase 3):** if the free-derived W4 feed screens insufficient, buy a paid EPS/guidance feed, or accept Conc's ceiling?
- **D3 (Phase 1):** if Main is `structural_unreachable`, hold the −25% mission bar (Main stays failing until pit-clean/universe change) or re-underwrite Main's mandate?

**What is explicitly NOT on the roadmap:** new technical indicators, more rank/RS/revenue variants, any falsified lever, any fullrun before a parity-substrate gate-passing candidate + user approval, any production/public wording before pit-clean.

## Verdict gates Claude will check per phase

- P0: `parity_exact` or quantified residual; XNYS wired at both call sites; #218 merged.
- P1: parity baseline published; Main verdict (`lever_found` | `structural_unreachable`) with joint+multi-era evidence.
- P2: pit blocker collapsed to `proxy_accepted` or paid clean file; survivorship delta quantified; D1 surfaced.
- P3: source `research_ready` + OOS screen result; if pass, gate-passing Conc candidate; D2 surfaced if insufficient.
- P4: alarms fire on fixtures; cron empty-input safe; ledger hashed append-only; CI baseline lock.
- P5: gate-chain honored; simulated-data labels on every number; fallback published pre-drawdown.
