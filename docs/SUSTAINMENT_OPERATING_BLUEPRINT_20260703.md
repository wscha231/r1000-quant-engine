# Sustainment Operating Blueprint — keeping CAGR/MDD alive through future regimes

> Author: Claude Code (web), 2026-07-03. Capstone over `CODEX_SYSTEM_AUDIT_AND_MASTER_PLAN_20260702.md` (W0–W7)
> and `GOVERNANCE_DECISIONS_W0_20260702.md`. Design principle: **returns cannot be made volatility-immune;
> the PROCESS can.** Everything below is grounded in this project's own measurements — nothing revives a
> falsified lever.

## 0. What sustains returns (measured) vs what does not (measured)

**Sustains (keep, protect):** regime-agnostic selection signals (RS/leader-tier/industry rotation — sector-blind
by construction, so leadership change is survivable); permanent cash buffer (bull-floor falsification proved it
load-bearing); monthly rotation cadence (every faster price-triggered variant lost: intramonth event exits
CAGR 24%/MDD −43%); trend-state ladder (1w+3m RS WARNING → TRIM → dual-MA EXIT); cash-carry accounting;
fixed-book A/B measurement discipline; negative-evidence ledger.

**Does not sustain (never rebuild):** crash prediction (VIX/DD breakers shipped and dormant); more technical
indicators (238 features already; every broad timing/sizing overlay measured negative); tighter stops; broad
cash redeployment; unconfirmed "confirmation" filters (EPS-revision proxy was an OOS counter-signal).

**The real threats to future returns are, in order:** (1) signals stop being executed (ops failure — the June
EXIT_REVIEW → July crash episode); (2) alpha decay goes undetected (no alarms yet); (3) overfit right-tail
(OOS/IS 3–5x) meets a regime it never trained on; (4) data rot (stale caches, broken cron). Note: none of these
is "not enough indicators."

## 1. Monitoring layer — the health metrics that matter (small, cheap, decisive)

Track these DAILY into the forward ledger (they are health metrics, not alpha features — do not feed them back
into scoring):

| Metric | Question it answers | Alarm basis |
|---|---|---|
| rolling 12m excess vs SPY (TR) | is the edge alive? | vs expectation band (bootstrap cone) |
| drawdown-budget consumption | how much of −25% is used? | % of budget, velocity |
| monthly pick hit-rate / 126d excess of picks | is selection still working? | rolling vs historical IS dist |
| cluster concentration (HHI by industry) | single-theme fragility | vs backtest historical range |
| signal→action lag (days) | are we executing? | SLA breach (see §3) |
| turnover, avg cash, position count | process drift | vs baseline envelope |
| data freshness (price/macro/SEC), coverage count | substrate rot | existing audits → alarm wiring |
| run determinism hash-match (post-W1) | can we trust deltas? | mismatch = block experiments |

Existing infra to reuse: `latest_price_date_audit`, `data_coverage_gate`, `daily_market_snapshot`,
`weekly_evaluation`, Telegram alert step. The gap is only wiring these into ONE ledger + alarm evaluator.

## 2. Alarm & fallback ladder — what to do when the logic stops working (차선책)

Pre-defined, published BEFORE the drawdown, so no decision is made in panic. Fallback asset = benchmark + T-bill
(the honest floor: worst case you degrade to SPY+cash-carry, a respectable outcome — not zero).

| Level | Trigger (evaluated weekly) | Automatic response | Human decision |
|---|---|---|---|
| 0 normal | inside expectation band | none | monthly review |
| 1 watch | rolling 12m excess < band p25, or DD budget >60% used | alert; review cadence → weekly; no trading change | acknowledge |
| 2 decay alert | excess < p10 for 2 consecutive months, or DD budget >85% | **strategy allocation −25%** (proceeds → SPY/T-bill), freeze new experiments | approve within 2 trading days |
| 3 kill-switch | portfolio DD breaches −25% contract, or 3 consecutive quarters below band, or data-integrity failure | strategy allocation → 50% floor, remainder SPY+T-bill; production/publication claims suspended | full re-underwrite required to re-engage |

Rules: de-risk by **allocation, never by ad-hoc name-picking** (falsified); re-engagement requires the same
gates as initial promotion; every level transition is a ledger row (auditable). Level definitions are versioned
in config, not prose.

## 3. Automation cadence — tiered by cost (GitHub Actions budget-aware)

| Tier | Cadence | Job | Cost | Status |
|---|---|---|---|---|
| T1 | daily, after close | data update → daily snapshot → review flags → **Telegram alert on WARNING/EXIT/alarm** → ledger append | minutes | exists except alert-wiring + ledger |
| T2 | weekly | weekly evaluation + expectation-band check + alarm evaluator + branch/PR staleness report | ~30 min | **cron BROKEN (empty-input bug) — fix is now service-critical, reverse the deferral** |
| T3 | monthly (1st trading day) | rebalance fullrun (fast_mode) → target book → **human approval SLA: 2 trading days** → execution decision logged | 3–5 h | exists; needs W5 completion split + SLA |
| T4 | quarterly | full validation suite, walk-forward re-verify, PIT membership audit, model retrain **challenger vs champion**, queued fixed-book A/Bs | hours | scaffolded (`auto_policy_challenger`, `auto_learning_promote` exist) |

**Review SLA (the fix for "signal existed, nobody acted"):** every EXIT_REVIEW/WARNING and every alarm level ≥1
must be human-resolved (execute/override, with reason) within 2 trading days; unresolved flags escalate daily
via Telegram; resolution + lag recorded in the ledger. The June-signal/July-crash episode is the canonical
counterexample this prevents.

## 4. Continuous improvement loop — how the system upgrades itself without self-harm

Champion/challenger with the discipline we already enforce manually:
1. **Idea intake** → must cite a measured artifact (audit finding, attribution gap), not a hunch. AI-taxonomy
   and screens are diagnostic inputs here.
2. **WIP limit = 2 experiments in flight** (one alpha, one ops). This is the anti-"doc loop" rule — the last
   month proved unbounded parallel ideas produce documents, not deltas.
3. **Cost ladder (never skip a rung):** cheap screen (minutes) → fixed-official-book replay A/B (~30 min) →
   only a gate-passing candidate earns one fullrun → ship gate (ΔCAGR ≥ +0.5pp, ΔSharpe ≥ −0.05, ΔMaxDD ≥ −3pp,
   OOS/IS not worse, ≥2 eras, Main non-regress, applied>0 no-op proof).
4. **Every experiment terminates in a verdict** recorded in the negative-evidence ledger (rejects are assets:
   bull-floor/hold-delay/sizing closeouts already prevent re-litigation).
5. **Quarterly model refresh** as challenger: retrain on extended window (post-W1 determinism, post-W2 PIT),
   promote only if challenger beats champion on the same gates. Never hot-swap.
6. **Baseline locks in CI:** current baseline metrics asserted in smoke tests; any PR that moves them without a
   verdict doc fails CI.

## 5. Cost-efficiency rules

- **Compute:** fullruns are the scarce unit (~6h wall). Budget: 1/month scheduled (T3) + max 1/month
  experimental (only gate-passing candidates). Everything else replay-stage or cached. Fix W5 split so a
  valid run never dies at the 5h50m wall.
- **Data:** free tier (yfinance/FRED/EDGAR) is sufficient for research + internal service. Paid spend only when
  it unblocks a gate: (a) PIT membership source (production blocker — the ONE data purchase with proven ROI),
  (b) EPS/guidance feed (only after W4 diagnostic shows the free EDGAR-derived version is insufficient),
  (c) commercial price license (only at public-service launch).
- **Attention (the scarcest resource):** batch decisions monthly; exception-driven alarms only (no daily noise);
  the three-engine review loop (Codex/Claude/GPT-Pro) reserved for verdicts and governance, not brainstorming.
- **Maintenance:** branch/PR triage quarterly (P0 index re-run); stale >90-day branches auto-flagged; docs
  superseded get a header pointer, not deletion.

## 6. Sequenced build-out (delta over the W-plan — mostly wiring, not new inventions)

1. **S1 (now, with fullrun #239 in flight):** fix T2 weekly cron (the deferred empty-input bug); wire Telegram
   alerts to EXIT_REVIEW/WARNING; start ledger append (W7 seed exists).
2. **S2:** expectation-band generator (block bootstrap of monthly returns) + alarm evaluator with §2 levels in
   config; drawdown-budget tracker.
3. **S3:** review-SLA mechanics (flag → notify → resolve-or-escalate → ledger).
4. **S4:** champion/challenger quarterly harness on the existing auto_learning scaffolding, gated per §4.
5. **S5 (post-W1/W2):** determinism-verified baselines + PIT-clean universe → alarms become trustworthy →
   restricted-beta service per governance (3 monthly cycles), public at 6–12 months ledger + compliance.

## 7. Non-negotiables (inherited, unchanged)

No production promotion while `pit_universe_label_clean=false`; no live trading without explicit user
enablement; falsified levers stay closed; de-risking by allocation only; forward returns audit-only; current
holdings are process outputs, not forward promises; every public number carries the simulated-backtest data
contract labels.
