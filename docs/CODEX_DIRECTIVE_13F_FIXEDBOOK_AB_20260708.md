# Codex Directive — 13F Fixed-Book Broker A/B (Concentrated)

> Author: Claude Code (web reviewer), 2026-07-08. Consumes the PR #237 source-
> screen packet (`outputs/run287_conc_alpha_source_packet/`). This authorizes
> **exactly one** cheap fixed-book broker A/B on a single source. It authorizes
> **no fullrun, no hook promotion, no production change, no threshold grid.**

## 0. Why this candidate, and only this one

Source-screen evidence (miss-set = 51 rows / 40 tickers, cap_or_replacement):

| Source | Coverage | OOS high-low | Status |
|---|---|---:|---|
| Form4 | 212 tk (sparse) | **−1.12%** (reverses OOS) | **dead — do not test** |
| SEC statement tilt | broad | already A/B'd: full +1.16 / **OOS −3.06** | **dead — do not retest** |
| combined (F4+13F+SEC) | 744 tk | +0.72% | **worse than 13F alone — do not test** |
| consensus | 58 OOS (sparse) | +1.20% but **hit 50.0%** | **coin-flip — do not test** |
| **13F** | **689 tk (broad)** | **+1.69% (best, OOS-positive)** | **the one candidate** |

Only **`w4_13f_score` (pure)** survives out-of-sample with broad coverage. The
mechanism is coherent: quality-manager accumulation is orthogonal to the
price-momentum/RS/revenue ranker that candidate-1 proved cannot reach the
miss-set alpha. **Test 13F pure. Do not blend** (the combined arm is diluted by
the two dead sources).

Base rate is sobering: 2 of 4 W4 sources are already dead, and SEC died in
exactly this A/B format (full-window positive → OOS negative). Treat this as a
~1-in-3 shot whose value is that it is **cheap and decisive**, not a likely win.

## Non-negotiables

No fullrun. No production promotion / live trading / public "beats S&P" wording.
No threshold grid (no tilt05/tilt10/tilt15 sweep). No forward returns in ranking.
No repair of specific losing months/tickers. No endpoint/window/benchmark
cherry-picking. Fixed official book only (R1 parity is not established — the
498-cache regenerated substrate is forbidden for this test). One clean design,
one verdict.

---

## G0 — PIT gate FIRST (pre-A/B; if this fails, the A/B is meaningless)

Before any replay, prove `w4_13f_score` is decision-time clean:

- **Verify the score uses each 13F's filing `accepted_ts` (available_from), not
  the period-end (report) date.** 13F is filed up to 45 days after quarter-end;
  using period-end holdings as-of the quarter is look-ahead that would inflate
  the +1.69%.
- Emit `outputs/run287_13f_pit_gate/summary.json` with:
  `available_from_field`, `uses_period_end` (must be `false`),
  `median_lag_days_period_end_to_available_from` (expect ~40–50),
  `rows_with_available_from_after_decision_date` (audit),
  `pit_gate_status ∈ {clean, leaky_period_end, blocked}`.
- **If `uses_period_end=true` → STOP. Fix the available_from wiring first; the
  screen's +1.69% is not trustworthy until then.** Do not run the A/B.

Acceptance: `pit_gate_status=clean` with lag ≥ ~40d, or the A/B is not run.

---

## G1 — A/B design: miss-set-targeted confirmation, NOT a universe tilt

The SEC arm died as a broad top-quintile tilt. Do not repeat that shape.

- Design the hook as a **replacement-quality confirmation on the
  `cap_or_replacement` miss-set** (reuse the existing fixed-book replacement-
  quality infrastructure): a candidate leader is swapped in **only when
  ex-ante 13F accumulation confirms**, using decision-time `available_from` rows.
- Default OFF (`PHASE_CONCENTRATED_13F_ACCUMULATION_CONFIRM_ENABLED`), single
  predeclared threshold (no grid). Preserve the cash buffer. Max 1 swap/date
  (match existing replacement-quality cadence).
- Substrate: **official fixed book** (`.../alphaops_vnext/official_concentrated_target_book.csv`),
  cash-carry AND zero-yield, replay end `2026-07-02`, no clamp change.

Files:
- 13F-confirm hook behind `phase_is_enabled` (reuse replacement-quality path)
- `tools/run287_13f_fixedbook_ab.py`
- `tests/run287_13f_fixedbook_ab_smoke.py`
- `outputs/run287_13f_fixedbook_ab/{summary.json, report.md, arm_metrics.csv, swaps.csv}`

## G2 — Statistical-power guard

The miss-set is only 51 rows → too small for a miss-set-only OOS verdict. Require
**both** to point the same way:
- broad 13F OOS IC (thousands of rows — statistical power), AND
- miss-set overlap (does 13F accumulation ex-ante separate the miss-set winners
  from losers — mechanism).

Emit both in `summary.json` (`broad_oos_ic`, `miss_set_overlap_separation`). If
they disagree in sign → `inconclusive_underpowered`, do not promote.

## G3 — Acceptance gate (OOS-primary; all must hold)

Both prior W4 A/Bs improved full-window and died on OOS. Therefore:
- **OOS dCAGR ≥ 0** (hard; full-window improvement alone is NOT acceptance), AND
- OOS2 dCAGR ≥ 0, AND
- absolute MDD not breaching −25% on either accounting mode, AND
- SPY-relative diagnostics reported (excess CAGR, down-capture, beta-adjusted
  alpha, relative MDD) — reported, not gated, AND
- applied-count > 0 no-op proof (swaps actually occurred), AND
- effect present on both cash-carry and zero-yield.

**Verdict labels:** `13f_confirm_candidate_pass` (→ eligible for one approved
fullrun later) | `reject_oos_worse` | `inconclusive_underpowered`.

**Pre-commit:** if OOS dCAGR < 0 (the SEC/Form4 fate), close `w4_13f_score` as
negative evidence and record that Concentrated is blocked on a true PIT
revision/guidance feed (D2 paid-data decision). Do not iterate thresholds.

---

## Sequencing

G0 (PIT gate) → only if `clean`: G1 design → G2 power guard → G3 verdict. One
pass. No fullrun until `13f_confirm_candidate_pass` AND user approval. Merge
PR #237 first (clean evidence packet; Form4/SEC negative evidence are assets).

## Verdict gates Claude will check

- G0: `pit_gate_status=clean`, lag ~40–50d, `uses_period_end=false`.
- G1: fixed official book, miss-set-targeted (not universe tilt), single threshold, cash preserved.
- G2: broad OOS IC and miss-set separation agree in sign, else `inconclusive_underpowered`.
- G3: OOS AND OOS2 dCAGR ≥ 0, absolute −25 intact both modes, SPY-relative reported, applied>0. Reject on OOS-worse → negative evidence, no grid.
