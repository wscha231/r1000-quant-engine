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

Implementation note: the policy hook now supports
`R1000_CONC_REPLACEMENT_QUALITY_EVENT_ALLOWLIST=<fixed_swaps.csv>`. When set, it must only admit
allowlisted `(rebalance_date, added_ticker, removed_ticker)` events and must force the donor to the
allowlist `removed_ticker`. This is the only hook mode eligible for A1 acceptance; the older
policy-month-rejection source remains diagnostic/backward-compatible only.

Latest status: allowlist mode removed the over-fire blocker (`policy-only hook events = 0`) but still
under-fires (`12/17`, count delta 29.41%) because five fixed-book donor tickers are not present in the
generated policy book. Do not choose alternate donors. Continue via W1/official-book event-source
reproduction, or keep this as fixed-book evidence only.

W1 donor audit confirms the five missing events are all
`generated_book_missing_fixed_donor`: the added candidate exists and the donor exists in the fixed official
book, but the donor is absent from the generated policy book and the exact policy rejection event is absent.
Therefore the next automatic step is not another alpha screen; it is either target-book control reproduction
or an official-book event-source path for this research hook.

Existing W1 root-cause evidence already points to provenance drift: same-machine double reproduction is exact,
but official-vs-generated control fails because the official artifact came from dirty commit `2f83cc8` while the
current reproduction is clean `4c54e630+`. Treat regenerated selection-side evidence as diagnostic until a clean
official control artifact is produced or the dirty worktree is reconstructed.

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
>40% warn / >45% block**, **absolute top3 >85% warn / >90% severe-warn**, gain concentration
top-added-ticker >35% warn / >50% block, top-era or top-year >70% block, **top-bucket Δ>+10pp warn**
(cluster crash lesson). Wire into the hook + smoke.

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
