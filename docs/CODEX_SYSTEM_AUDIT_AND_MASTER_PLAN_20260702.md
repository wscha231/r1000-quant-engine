# System Audit & Master Plan — data → universe → scoring → selection → measurement → ops

> Author: Claude Code (web), 2026-07-02. Full-stack audit of the AlphaOps vNext system with a prioritized,
> gated work program for Codex. Supersedes prior sequencing docs for planning; measurement discipline stays
> per `docs/CODEX_MEASUREMENT_PROTOCOL.md`.

## 0. Goal & verified position

**Mission (broker_ledger_next_close, valid_7y):** Main CAGR ≥ 35% & MDD ≥ −25% · Concentrated CAGR ≥ 50% & MDD ≥ −25%.

| | CAGR | MaxDD | Status |
|---|---:|---:|---|
| Main (+cash-carry, research) | **35.11%** | −23.99% | headline PASS (research accounting) |
| Concentrated (+cash-carry) | **48.83%** | −23.79% | **−1.17pp** short |
| tier-2 strengthened | IS CAGR 23–25% (< floors), OOS/IS 3.1–4.9x (> 3.0) | | **FAIL — the real wall** |
| production | `pit_universe_label_clean=false` | | **BLOCKED** |

**Falsified (closed, do NOT retry):** broad bull-floor/gross-floor · broad hold-delay/exit-delay · cap-safe
risk-adjusted sizing (11 arms, all reject). Concentrated cash is load-bearing MDD defense; the winner-
concentrated right tail is load-bearing CAGR.

---

## 1. Layer-by-layer audit (verified facts → gap → required work)

### L1. Data collection (free-tier: yfinance, FRED, SEC EDGAR, Alpha Vantage 25/day)
- ✅ Works: adjusted-close total-return prices; FRED macro (15 series incl. dgs3mo since #214-follow-up);
  SEC companyfacts (PIT accepted-ts); Form4; replay-cache manifest honesty (end = observed bars).
- 🔴 **Gap A — PIT EPS estimate/guidance feed does not exist.** `revision`/`actual_results_score` are
  companyfacts-derived actuals, not analyst estimates. The cheap revision proxy is an OOS **counter-signal**
  (+14.2% confirmed vs +17.1% unconfirmed) — building confirmation hooks on it is unjustified.
- 🟡 Gap B — ETF N-PORT 0% pre-2020 (hard floor), 13F needs CUSIP→ticker, delisted-name prices absent
  (yfinance) → early-era evidence degraded; relevant to any 10Y/IS-extension work.

### L2. Universe construction — **the production blocker lives here**
- 🔴 **`universe_fallback_mode="current_constituents"` (`r1000_config.py:1803`) = survivorship root** →
  `pit_universe_label_clean=false` → production permanently blocked regardless of CAGR.
- ✅ Tooling already exists but has never been run to completion with real inputs:
  `tools/build_pit_membership_by_month.py`, `tools/run_pit_membership_audit.py`.
- Required: source historical R1000 membership (archived IWB holdings snapshots / any free constituent
  history; ceiling honestly documented — free tier may cap at proxy-label), build monthly membership file,
  pass the audit, flip the label. This is the ONLY path to production evidence.

### L3. Scoring / ML (238 features, Ridge+LogReg+CatBoost, walk-forward 126d embargo)
- ✏️ **CORRECTED (Codex review, verified):** the engine IS seeded — `cfg.random_seed=42` is wired into
  Ridge/LogReg/CatBoost (`r1000_pipeline.py:9969–10059, 12560`). My earlier "no seed anywhere" claim grepped
  the wrong file (`r1000_top30_institutional.py`, 0 matches). W1 is therefore a **control-reproduction
  root-cause investigation, not a seed patch.**
- 🔴 **Verified environment-nondeterminism suspect #1:** `choose_catboost_task_type()`
  (`r1000_pipeline.py:9295–9298`) auto-selects **GPU when available, else CPU**. CatBoost GPU training is
  nondeterministic even with a fixed seed, and GPU-vs-CPU trains different models outright. The official
  artifact came from a CPU GitHub runner; regeneration happens on local/Colab (GPU-capable). This alone can
  explain the 25-date ticker mismatch and contributes to Main run-to-run drift (35.28 → 34.27).
  Other suspects to bisect: input-snapshot drift (candidate source, SEC-enriched vs not, cache freshness,
  appended dates, macro/crisis inputs), library versions, unstable sort/rank tie-breaking.
  **A ±1pp-noisy base makes every "target pass" claim unstable.**
- 🟡 Overfit structure: OOS/IS 3.1–4.9x, weak IS — gains concentrated in the 2024-25 right tail. Longer-IS
  (proxy-10Y track doc exists) and era-robust gates are the structural fixes, gated on L2.

### L4. Selection / replacement (vNext sleeves, candidate gates, hysteresis)
- ✅ Signals are **sector-agnostic by construction** (rs_industry_*, oneil_leadership_score, leader-tier vs
  SPY/QQQ, industry_rotation_signal) → rotation-capable when leadership changes; current AI concentration is
  an OUTPUT of momentum signals, not a hardcoded bet. Keep it that way — AI-capex taxonomy stays a
  diagnostic lens, never a selection predicate.
- 🔴 Unmeasured: **rotation latency** (how many months from a new leader's RS emergence to first entry) and
  **replacement quality** (are the 1,654 candidate-gate + 656 cap/replacement rejections dropping future
  winners?). This is where the missing Conc +1.17pp most plausibly lives, since gross/hold/sizing are all
  falsified.
- Blocked: any regenerated-book selection A/B until L3 determinism is fixed (control non-repro).

### L5. Portfolio / risk (dual sleeve, cash policy, SH hedge)
- ✅ Cash defense validated (bull-floor falsification proved it load-bearing). SH fast-crash hedge fires
  (2 dates) but is **fragile by protocol §4** (≤2 events) — needs hedge-OFF isolation A/B before credited.
- ✅ Cash-carry accounting implemented, measured, guarded (freshness, end-clamp, no-op) — awaiting governance.

### L6. Measurement / replay — **now the strongest layer**
- ✅ broker-ledger canonical; valid_7y window gate (#213); cash-carry mode (#214); target-ticker freshness +
  end-date clamp + `end_date_matches_official`; fixed-official-book A/B harness (correct control);
  control-repro audit tool. Nothing to add here.

### L7. Ops / contracts / CI
- ✅ Fixed this cycle: canonical operating-book target + snapshot hash; target_price_coverage safety audit;
  user_current/preview contract verify.
- 🔴 Open: fullrun 5h50m timeout (critical-path vs research-sidecar split, fail-fast placement, preflight
  status.json persistence); weekly `schedule:` runs crash on empty inputs (fast_mode='' — deferred by user);
  results stranded on local H:\ instead of committed GitHub artifacts for some steps.

---

## 2. Work program (gated; cheap-first; one measurement per step)

### W0 — Governance decisions [USER, not Codex — blocking]
1. **Adopt cash-carry as official research baseline?** (contract draft exists). If yes: re-baseline all
   comparisons, keep zero-yield side-by-side, production still blocked. *This decision is worth more than the
   remaining 1.17pp.*
2. Target-contract cleanup: `target_contract_status="unresolved_user_decision_required"` (interim −28% vs
   canonical −25% Conc MDD) — pick one, record it.

### W1 — Control-reproduction root cause [Codex, HIGHEST engineering priority]
Goal: same inputs → identical target book; official metrics stable run-to-run. (Seeds already exist — this is
an investigation, per Codex's correction.)
Bisection order (cheapest discriminator first):
1. **Environment parity:** record + compare `task_type` (GPU/CPU), CatBoost/sklearn/numpy versions between the
   official run and regeneration. Add both to `run_manifest.json`. Repro mode forces `task_type=CPU` (and a
   pinned `thread_count`) — GPU CatBoost is nondeterministic even when seeded.
2. **Input snapshot hashing:** hash feature_store, candidate books (SEC-enriched vs not), price/macro cache
   manifests, appended operating dates — official vs regenerated. Any diff → fix the snapshot path first.
3. **Same-machine repeatability:** regenerate twice locally back-to-back; if books differ with identical
   inputs+CPU, hunt residual RNG/threads/unstable tie-breaking (sort/rank/groupby).
- Acceptance: control-repro audit → 0 official-only / 0 generated-only / 0 ticker-mismatch dates, max weight
  Δ ≈ 0; a deterministic failure table documenting which layer caused what.
- Unblocks: all selection-side A/B (L4), trustworthy baselines, Main drift explanation.

### W2 — PIT universe membership [Codex, long-running parallel — the production path]
- Source historical R1000 membership → `build_pit_membership_by_month.py` → `run_pit_membership_audit.py`
  green → replace `current_constituents` fallback. Honestly cap what free data can prove; if the ceiling is
  proxy-label, document it and present the paid-data decision to the user.
- Acceptance: audit passes (no current_constituents_proxy/static_seed/future available_from), coverage ≥400/mo.

### W3 — Rotation & replacement-quality diagnosis [Codex, cheap, this week]
- `run_leadership_rotation_latency_audit.py`: per era (2019 SaaS→2020 covid→2021 reopen→2022 energy/defense→
  2023-25 AI), months from new-leader RS emergence → first portfolio entry; portfolio share in top-RS
  industries per era. Answers "can we handle leadership change" with data.
- Replacement-quality: join the 1,654/656 rejection log with forward-return audit labels (audit-only) — are
  gates dropping future winners? Which gate?
- Output feeds ONE narrow, default-OFF, bucket-agnostic hook candidate (leader-tier + RS + actual-results
  predicate) measured on the fixed-official-book harness with OOS/IS + multi-era gates.

### W4 — PIT EPS/guidance feed [Codex, medium]
- Build from EDGAR first (8-K/press-release actuals + companyfacts revisions, accepted-ts PIT); evaluate free
  estimate sources; only then re-test "earnings-confirmed" hooks. Until then, no revision-gated logic.

### W5 — Fullrun completion engineering [Codex, before the next fullrun only]
- Split critical path (rebuild → official metrics → books → safety → commit) from research sidecars (~73min
  goal-search) into a second job; fail-fast contract check right after book generation; persist preflight
  status.json; time budget with margin under the 6h wall.

### W6 — Overfit reduction [after W1+W2]
- Proxy-10Y IS extension (doc exists) + era-robust ship gates; success = OOS/IS ratio falls toward ≤3.0 and
  IS CAGR clears floors. This — not the last 1.17pp — is what makes the numbers production-quality.

### W7 — Forward-service readiness [new layer — backtest→future pivot]
Everything above validates the PAST. A public website showing current holdings needs a FORWARD layer:
1. **Live forward-tracking ledger:** paper ledger from a declared freeze date — daily NAV, monthly
   rebalances as the system actually emits them, vs SPY total return. This forward record (not the backtest)
   is the service's only honest credential. Start it NOW so history accumulates.
2. **Expectation bands, not point targets:** block-bootstrap monthly returns → 12/36-month percentile cones.
   The site shows "current position vs band," never "50% expected." Honest central forward expectation is
   IS-CAGR (~23–25%), not the OOS-heavy headline; 35/50 is the favorable-regime upper band.
3. **Alpha-decay & regime alarms + kill-switch criteria:** rolling 12m excess vs band floor, drawdown-budget
   tracker (Conc has only ~1.2pp MDD headroom; 5 names, SNDK ~39% — one earnings miss moves pp), predefined
   "stop trusting this" rules published with the service.
4. **Automation hardening becomes mandatory:** the weekly `schedule:` crash (empty inputs, previously
   deferred) and W5 fullrun completion are service-critical — no reliable auto-refresh, no service.
5. **Immutable published-snapshot audit:** hash + timestamp everything shown (target_snapshot_hash already
   exists — reuse). Forward performance claims must be verifiable against what was actually displayed.
6. **Data licensing:** yfinance ToS is a problem for a commercial service; review sourcing before launch.
7. **Labeling discipline:** `pit_universe_label_clean=false` backtest numbers may NOT be marketed as
   performance; simulation/research-only disclaimers; check KR advisory regulations (유사투자자문).
8. Foundation already laid: the user_current contract outputs (01_current_holdings, 02_target_weights,
   snapshot hash, review_only flags) are the website's read-only API surface.

### Standing rules
- Fullrun ONLY when: a replay-stage candidate passes gate on fixed-official-book control AND W5 done AND user
  greenlights. Falsified levers stay closed. AI taxonomy = diagnostics only. Every lever: env-gated default
  OFF, applied-count no-op proof, gate-first champion, OOS/IS + ≥2-era robustness, Main non-regress.

## 3. Sequence
```
now:      W0 (user) ─┬─ W3 (cheap diagnosis) ─→ one narrow hook candidate → fixed-book A/B
                     ├─ W1 (determinism)     ─→ unblocks selection A/B + stable baselines
                     └─ W2 (PIT membership, long-running)
then:     W4 (EPS feed) · W5 (fullrun eng) → one fullrun when a candidate passes
finally:  W6 (overfit/10Y) → production evidence = W2 + W6 + stable W1 baselines
```
