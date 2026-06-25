# Codex Measurement & Acceptance Protocol — real CAGR/MDD gains under strict measurement

> Handoff: Codex (local). Author: Claude Code (web), 2026-06-25.
> Companions: `docs/CODEX_RESEARCH_LEADER_CAPTURE.md`,
> `docs/CODEX_PLAN_FORWARD_TIMING_OPTIMIZATION.md`,
> `docs/CODEX_DIRECTIVE_CAGR_MDD_ROADMAP.md`, `CLAUDE.md`.
>
> PURPOSE: make every lever prove a **real** CAGR/MDD improvement when measured with
> the STRICTEST replay — not a proxy mirage. We have already been fooled once: the
> PRWV / subdaily proxy reported Main −13.80% / Conc −13.33% MaxDD, but the broker-style
> account-ledger replay of the same run showed −25.01% / −25.82%. **A gain that only
> exists in a proxy is not a gain.** This document is the gate that turns "looks better"
> into "is better."

---

## 0. The one rule

A lever is "an improvement" ONLY if, on `broker_ledger_next_close` (full account ledger),
over a valid window, with the lever actually firing, it moves its target gap the right way
without breaking the other sleeve, survives walk-forward, and does not regress leader
capture. Anything measured on a weaker metric is a hypothesis, not a result.

---

## 1. Canonical metric (the ONLY metric that counts for acceptance)

**Accept on:** `outputs/broker_replay/<kind>/metrics.json` (`cagr`, `max_dd`, `sharpe`)
produced by `run_broker_ledger_replay.py` — integer shares, 25 bps cost, next-close fills,
`max-fill-lag-days 7`, cash ledger, daily equity curve. Cross-check the gate in
`outputs/account_evaluation/official_metrics.json`.

**Do NOT accept on (research-only, known to be optimistic):**
- weight-level / scored metrics (≈ +11pp optimistic MaxDD vs broker ledger).
- PRWV / `subdaily_exit_grid_*` (path-only, no account ledger) — the −13% mirage.
- `mdd_cash_overlay_research` overlays (post-hoc, not the operating book).

These proxies are fine for **cheap screening** (shortlist a config), but the number that
ships must be reproduced on the broker ledger. Strict trailing-stop grids must use
`run_broker_position_risk_grid_sweep.py` (account ledger), not the PRWV grid.

---

## 2. Window validity preconditions (no metric is real until these hold)

From `account_evaluation/official_metrics.json` `broker_ledger_window_gate`:
- `years >= 7.0` (or explicitly classified `research_7y_tolerance` ≈ 6.96y — never silently).
- `actual_trading_days >= 1764` for **BOTH** sleeves. NOTE: concentrated currently undercounts
  (equity-curve ROW count, not calendar trading days) — fix to calendar trading days in
  `[broker_start, end]` or this gate fails for the cash-heavy sleeve regardless of the start fix.
- `data_readiness.ready_for_policy_replay = true`.
- No future `available_from` leakage (every feature used at decision `t` has `available_from ≤ t`).
- `pit_universe_label_clean = false` is expected → production promotion stays blocked. That is
  acceptable for a research baseline; it does NOT invalidate a research_7y CAGR/MDD comparison.

If the window is invalid AND not classified as tolerance, do not report CAGR/MDD as a result.

---

## 3. A/B measurement protocol (how to get a trustworthy delta)

1. **Same source, one lever.** Baseline and treatment must use the SAME scored artifacts +
   price cache (reuse one rebuild — the lever acts at target-book/replay stage). Flip exactly
   ONE env flag (e.g. `PHASE_SHAKEOUT_GUARD_PROD_ENABLED`); everything else identical. Never
   co-enable two new levers in the first A/B (isolate; e.g. shakeout vs persistence-hold).
2. **No-op proof FIRST.** The treatment must show the lever fired:
   `<lever>_applied = True` row count `> 0` in the target book. If it is 0, the result is a
   WIRING NO-OP, not "no effect" — stop and check the gating fields are populated on replay
   rows (e.g. `leader_tier`, `sector_leadership_score`, `smart_money_evidence_confidence`).
3. **Delta on the canonical metric.** ΔCAGR, ΔMaxDD, ΔSharpe = treatment − baseline, read from
   `broker_replay/<kind>/metrics.json`. Use the lever-sweep harness for cheap multi-value grids;
   a full rebuild is needed only for changes to scoring/feature_store, not for replay-stage levers.
4. **Both sleeves reported.** A lever that helps one sleeve and breaks the other is not a ship.

---

## 4. Generalization & anti-overfit (so the gain is real forward, not fitted)

- **Walk-forward + 126d embargo**: the improvement must appear in the OOS fold(s), not only
  full-period. A lever whose gain vanishes OOS is rejected.
- **Not one era / one name**: check `trade_attribution/<kind>/` per-era contribution. For a
  growth/concentrated book, right-tail concentration is acceptable **only if** the winners were
  identifiable ex-ante by PIT signals and repeat across ≥3 eras (skill, not luck). Reject if the
  whole gain is a single era or a single name, or pure SPY/QQQ/SMH/SOXX beta.
- **Risk levers must not rest on 1–2 events**: for stop/trailing levers, report per-era
  `risk_exit_count`. A −1pp MaxDD that comes from 2 stop events in 7 years is fragile, not robust
  — require the benefit to recur across eras.
- **No answer-sheet**: no hardcoded tickers/dates/sectors/thresholds-fit-to-known-crashes.

---

## 5. Grid champion selection (gate-first, never crown a violator)

When sweeping a grid (trailing stop, gross floor, thresholds):
1. Filter to **hard-gate-passing** configs first: `max_dd >= -0.25` AND `cagr >= target`
   (main 0.35, concentrated 0.50).
2. Rank by composite only WITHIN that passing set.
3. If none pass, emit `champion = None`, `status = "no_gate_passing_config"` — still publish the
   full ranked surface, but do not present a gate-violating config as the champion. (PR #158's
   composite crowned Conc −30% at MaxDD −25.82% — that must not happen.)

---

## 6. Per-lever measurement plan (what "improvement" means for each)

| Lever | Target gap | Strict measurement | Pass condition |
|---|---|---|---|
| A1 SHAKEOUT_GUARD (PR #161) | hold winners → CAGR | broker A/B, env ON | applied>0; premature_sell/EXIT_REPLACE 126d excess ↓; pct_held_365d_plus ↑; ΔCAGR ≥ +0.5pp; ΔMaxDD ≥ −3pp; capture non-regress |
| A2 earnings state gate | hold earnings-strong / cut earnings-broken | broker A/B | applied>0; realized loss-before-exit ↓ on broken names; ship gate; capture non-regress |
| Gross floor (Conc) | Conc CAGR +4pp | lever-sweep grid + broker, gate-first | Conc ΔCAGR ≥ +1.0pp; 2022 defensive cash UNCHANGED; ΔMaxDD ≥ −1pp |
| Trailing stop (Main) | Main MaxDD −1pp | `run_broker_position_risk_grid_sweep.py` (account ledger), gate-first, per-era exits | Main MaxDD ≥ −25; per-era exit_count > 1; OOS holds; ΔCAGR ≥ −0.5pp |

For each: read `entry_exit_timing_audit/` (premature_sell, pct_held_365d_plus, EXIT_REPLACE
126d excess) and `stock_selection_quality/theme_leader_capture.csv` alongside the broker metrics.

---

## 7. Definition of "real improvement" + final target proof

**Per-lever ship gate (all required, on broker_ledger_next_close, valid window):**
- `applied > 0` (fired), AND
- ΔCAGR ≥ +0.5pp AND ΔSharpe ≥ −0.05 AND ΔMaxDD ≥ −3pp, AND
- moves its sleeve's target gap the right way without breaking the other sleeve's passing metric, AND
- `theme_leader_capture` non-regress, AND
- survives walk-forward (OOS fold improvement, not full-period only).

**Final target proof (research baseline "achieved"):** ONE valid (or tolerance-classified)
fullrun with the shipped levers combined, on `broker_ledger_next_close`, showing simultaneously:
- Main: CAGR ≥ 35% AND MaxDD ≥ −25%
- Concentrated: CAGR ≥ 50% AND MaxDD ≥ −25%
- ship gate + generalization gates pass, leakage 0.
Production promotion remains separate (needs `pit_universe_label_clean`).

---

## 8. Guardrails (unchanged)

PIT-only; env-gated default OFF; new feature columns into `build_feature_store.keep_cols` +
`hard_sanitize` + phase zero-placeholder (else silently 0.0); CI smoke in the same commit;
no live / production mutation / T3 / recovery / proxy 8Y-10Y. Cheap-first: proxy/lever-sweep to
shortlist, broker ledger to accept, full rebuild only when feature_store changes.

---

### TL;DR for Codex
1. Screen cheap (proxy / lever-sweep) → 2. **prove `applied>0`** → 3. measure ΔCAGR/ΔMaxDD on
`broker_replay/*/metrics.json` over a valid window → 4. confirm OOS + per-era + capture
non-regress → 5. only then call it an improvement. A proxy gain (PRWV −13%) that does not
reproduce on the broker ledger (−25%) is **not** a gain.
