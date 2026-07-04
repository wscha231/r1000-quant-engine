# FAST-TRACK Performance Directive — 2026-07-04

> Purpose: **stop the review ping-pong and raise performance fast.** Every task below carries pre-authorized
> decision rules — if the gate passes, PROCEED to the next step WITHOUT external review. Batch ALL results into
> ONE weekly review packet. External review (Claude/GPT-Pro) is only for: gate-ambiguous outcomes, governance
> reopens, and the final fullrun go/no-go.

## Standing state (do not re-derive, do not re-ask)
- Governance BINDING: cash-carry = official research baseline (zero-yield side-by-side) · MDD −25 both sleeves ·
  Main long-only (SH → backlog). Production blocked by `pit_universe_label_clean=false`.
- FALSIFIED, never revisit: broad bull-floor/gross-floor · broad hold/exit-delay · cap-safe sizing · crash
  prediction · tighter price stops · revision-proxy confirmation gates.
- PROVEN: cash-carry (+0.84 Main / +1.37 Conc, MDD also better) · replacement-quality counterfactual
  (+1.2~1.9pp Conc, concentration-neutral, multi-era, IS-positive, cross-book).
- Current gaps: **Main is now the failing sleeve on the latest book** (30.61/−26.02 crash-inclusive, confounded);
  Conc 44.53→~46-49 w/ carry, candidate closes the rest.

## Anti-ping-pong protocol (mandatory)
1. Each task has numeric DONE criteria. Pass → auto-proceed. Fail → record in the packet, move to the listed
   fallback. Ambiguous → park it, continue other tracks.
2. ONE review packet per week (or when Track A+B both terminate), containing: per-task gate table
   (pass/fail/value), swap/contribution logs, and the single decision that needs a human.
3. No new ideas mid-flight. Anything new goes to `BACKLOG.md` untriaged.
4. WIP: Tracks A–D are pre-authorized to run in this order with max 2 active; E–F are background.

---

## Track A — Concentrated: finish the proven candidate (target: official ≥50 / ≥−25)

**A1. Event-source reconciliation.** Make the policy-path hook consume the SAME event definition as the
fixed-book counterfactual (missed_leaders_audit-equivalent): same month, same cap/replacement class, rejected
ticker itself passes `leader_rank_ex_ante<=15 AND revenue_growth>=0.10`, max 1 swap/date, cash/gross preserved.
Emit `outputs/replacement_hook_equivalence/{hook_swaps.csv,counterfactual_swaps.csv,diff.csv}`.
- GATE A1: hook swap set ⊆ counterfactual swap set (validation window), count parity ±10%.
- Pass → A2. Fail → diff.csv names the divergent condition; fix and rerun once; still fail → packet.

**A2. Level reconciliation (kills the last measurement doubt).** Run `run_cash_carry_measurement` on the #239
(28616190134) book → official cash-carry level. Compare to the harness control (49.34).
- GATE A2: |harness_control − official_cash_carry| ≤ 0.3pp with a one-line cause note for any residual.
- Pass → the "clears 50%" claim is valid on BOTH books → A3. Fail → find the harness/official divergence
  (window/variant/fill) before quoting levels; deltas remain usable meanwhile.

**A3. Freeze + robustness table (one shot, no re-optimization).** Rule frozen: `rank_top15_and_revenue_ge10`.
Emit the adjacent-cell grid (rank 10/15/20 × revenue 5/10/15) from EXISTING outputs — no new sweeps.
- GATE A3: neighbors degrade smoothly (no cliff: best cell ≤ 2× second-best delta). Disclose total arms tried.
- Pass → A4. Cliff → downgrade to diagnostic, go Track C.

**A4. Concentration guards to config**: top1 Δ>+5pp warn, top3 Δ>+10pp warn, HHI Δ>+0.05 warn, **absolute top1
>40% warn / >45% block**, **top-bucket Δ>+10pp warn** (cluster crash lesson). Wire into the hook + smoke.

**A5. DONE(A) =** default-OFF hook, event-matched, fixed-book-accepted (gates A1–A4), documented. This becomes
the Conc fullrun payload. **Do NOT dispatch a fullrun** — that is the end-of-week human decision.

## Track B — Main: apply the same proven machinery to the failing sleeve (NEW, cheap, high value)

**B1. Hedge-OFF fixed-book replay** (the long-slipping T1 — 2h of work, run it FIRST): #238 Main book, SH rows
zeroed, `--replay-end-date 2026-06-29`, zero-yield + cash-carry.
- GATE B1: `end_date_matches_official=true`. Output hedge_on_vs_off deltas.
- If hedge-off Main MDD ≥ −25: long-only Main baseline is quotable → B2. If it breaches −25:
  `governance_reopen_required` → packet (this is one of the few true human questions).

**B2. Main missed-leader counterfactual** — run the EXISTING P4 harness
(`run_concentrated_cap_replacement_broker_counterfactual.py`, generalized `--portfolio main`) on the Main book,
both #238 and #239, cash-carry aligned, crash-inclusive end for #239. Main has its own cap/replacement
rejections; the tool already exists — this is the cheapest untested CAGR lever for the sleeve that now fails.
- GATE B2: any arm with ΔCAGR ≥ +0.5pp AND MDD ≥ −25 AND concentration-neutral AND multi-era (top era <60%,
  top name <50% of delta) AND IS delta ≥ 0.
- Pass → freeze that single rule, same A1-style event matching, add to the fullrun payload. Fail → packet
  (Main CAGR then depends on B1 + cash-carry + rotation Track C).

## Track C — Rotation stickiness: the live-crash counterfactual (next real alpha question)

**C1. Three-way broker replay through the crash** (data exists, no fullrun):
(i) June operating book held (actual), (ii) June RAW scored rotation (AMD/AMAT/GLW), (iii) July-02 actual
rotation — all through 2026-07-02+ with cash-carry.
- Output: `outputs/rotation_latency_counterfactual/{metrics.csv,report.md}` with CAGR/MDD deltas and per-name
  attribution.
- DECISION RULE: if (ii) beats (i) by ≥ +1pp CAGR without MDD damage → hysteresis stickiness is a REAL cost →
  authorize C2. Else → stickiness vindicated; close the question with the negative-evidence entry.

**C2 (only if C1 triggers). One narrow anti-stickiness rule**, fixed-book: allow an operating-book swap when the
raw-vs-operating score gap is extreme (e.g., incumbent falls below rank 25 AND challenger in top 10 for 2
consecutive months) — max 1 swap/month, review-only telemetry first. Standard ship gates. NO broad relaxation.

## Track D — State-triggered mid-month risk escalation (the untested no-op, crash-motivated)

**D1.** Re-run `accelerate_exit_if_deteriorating` with fields actually populated (dual-MA fail + 3m RS<0 +
thesis fields), fixed-book, both books, crash-inclusive.
- GATE D1: applied>0 this time; ΔMDD ≥ +0.5pp (better) with ΔCAGR ≥ −0.5pp, OOS holds.
- Pass → default-OFF hook candidate for the risk ladder (review-only intramonth trim). Fail with applied>0 →
  genuine negative evidence; close permanently (it joins the falsified family with data this time).

## Track E — Background (do not consume A–D slots)
- **E1. W1 root cause step ①only**: record+compare `task_type`/versions/threads (#238 GitHub runner vs local),
  force CPU repro mode, same-machine double-run hash check. This is ~1 day and may fully explain the 25-date
  mismatch. Steps ②③ only if ① fails to explain.
- **E2. Cash-carry native emission**: official workflow emits `broker_ledger_next_close_cash_carry` alongside
  zero-yield in `official_metrics.json` (governance-adopted; stop hand-running measurements).
- **E3. S1 wiring**: weekly-cron empty-input fix + backend alerts (`outputs/alerts/`) + forward-ledger append.
- **E4. W2 PIT membership** stays the production-critical data track.

## Track F — The weekly packet (the ONLY recurring review)
One file: `docs/WEEKLY_EXECUTION_PACKET_<date>.md` — gate table for A–E (pass/fail/value/next), the ≤3 genuinely
human decisions, and the fullrun go/no-go recommendation with its payload list (A5 + B2-if-passed + E2). Claude
verdicts THAT, once.

## Fullrun payload (assembled by the tracks, dispatched only on human go)
`PHASE_CONCENTRATED_REPLACEMENT_QUALITY_ENABLED=1` (A5) · Main rule if B2 passed · long-only (no SH) ·
cash-carry emission (E2) · fresh data · fast_mode · after W1-① env parity is at least recorded.
Success = official run: **Main ≥35/−25 AND Conc ≥50/−25 on cash-carry, valid_7y, contracts green** — the first
run that can claim the full mission headline (research; production still gated by W2).

## Hard rules
No falsified-lever revival · no rule re-optimization after freeze · no regenerated-book acceptance before W1 ·
no fullrun without the weekly-packet human go · no production/public claims (`pit_clean=false`) · forward
returns audit-only · all hooks default-OFF, applied-count proof, review-only actions.

---

## Track M — Momentum-identity research audits (2026-07-04 addendum; background tier, after A–D slots free)

Context: the system is, academically, a **concentrated long-only cross-sectional momentum + trend + industry-
momentum portfolio with fundamental confirmation and regime-managed cash** (Jegadeesh-Titman / Moskowitz-
Grinblatt / George-Hwang / Barroso-Santa-Clara lineage). The momentum literature's known failure modes map onto
us asymmetrically: the classic momentum CRASH (short-side loser rally, WML −73% in 2009) is structurally muted
because we are long-only; the long-only variant's real weakness is **post-trough re-entry lag** (cash watches
the V-rebound). These audits measure our actual exposure before touching any policy. **Audits only — any
resulting rule goes through the standard fixed-book gate chain. Do NOT import: short side, full 12-1 rebalance,
vol-scaling UP, 1-month-reversal entries, tight stops (all conflict with our falsification record).**

**M1. Momentum-beta decomposition** — build an internal 12-1 momentum factor from our own price cache (top-
minus-bottom decile of the R1000 universe, monthly), regress the strategy's monthly excess returns on
{MKT, internal-UMD}; report alpha vs momentum-beta share for Main and Concentrated.
- Purpose: quantify how much of our edge is generic momentum premium vs implementation alpha (selection,
  concentration, risk ladder). Feeds honest expectation bands (W7) and a `momentum_factor_neutral_excess`
  health metric in the forward ledger.
- No gate — informational. If momentum-beta explains >80%, our differentiation claim shifts to risk-managed
  implementation (state this in service disclosures).

**M2. Horizon IC audit** — IC (rank corr with 63d/126d forward audit labels) of each RS horizon feature
(1w/1m/3m/6m/12m, plus 12-1 echo) on the existing feature store. Flag any ENTRY-side positive weight on 1w/1m
horizons (academic short-term reversal territory; note our 1w-RS WARNING is an EXIT trigger — different, fine).
- DECISION RULE: if 1w/1m entry-side IC ≤ 0 while carrying positive scoring weight → one backlog candidate:
  demote those horizons at entry (feature-weight change ⇒ FULL-rebuild-class, so backlog until a fullrun is
  scheduled anyway; bundle then).

**M3. Post-trough re-entry lag audit (long-only momentum's #1 weakness)** — for 2020-03, 2022-10, 2024-08 and
the 2025 window: months from portfolio-equity trough to full re-investment; CAGR foregone in the first 63d/126d
post-trough vs (a) SPY and (b) hold-through counterfactual. Reuse `crisis_reentry_replay` machinery.
- DECISION RULE: if total foregone ≥ 1pp CAGR across episodes → authorize ONE narrow re-entry rule test
  (breadth-thrust style: e.g., % of universe above MA50 crossing a threshold accelerates redeploy), fixed-book,
  standard gates. Else → close with a negative-evidence note ("cash re-entry lag is cheap insurance").

**M4. Asymmetric volatility brake (the surviving half of vol-managed momentum)** — fixed-book test: scale
STOCK gross down (floor 60%) when realized 20d portfolio vol exceeds a high percentile of its own history;
NEVER scale up (this is what separates it from the falsified bull-floor) and portfolio-level only (separates it
from the falsified per-name vol_adjusted_weight). Both books, cash-carry, crash-inclusive.
- GATE: ΔMDD ≥ +1pp (better) AND ΔCAGR ≥ −0.5pp AND OOS holds AND fires in ≥2 stress eras. Pass → default-OFF
  hook candidate for the risk ladder. Fail → momentum vol-management is closed for this book (negative
  evidence; our regime-cash already captures it).

Ordering: M1/M2 are pure audits (can run in E-tier background). M3/M4 enter the A–D queue only when a slot
frees. Results go into the weekly packet like everything else.
