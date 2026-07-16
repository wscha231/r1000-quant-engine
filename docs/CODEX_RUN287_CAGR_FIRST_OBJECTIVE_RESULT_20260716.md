# Run287 CAGR-first objective result — 2026-07-16

## Decision

The user explicitly changed the research priority from the prior `MDD >= -25%`
gate to net geometric CAGR maximization.  This review therefore removed MDD
from pass/fail, but preserved OOS/OOS2, cost, provenance, and concentration
generalization gates.

The completed historical A/B inventory was re-scored before any new experiment.
No new signal, threshold, or tilt grid was created.

Final status: `REJECT_GROWTH_FIRST_CONCENTRATION`.

The best existing arm is economically interesting, but it is not a durable
promotion candidate because 59.59% of its net incremental P&L occurs in the
single `2025_plus` era.  The fixed 50% era concentration gate fails, so the
126-session embargo walk-forward was not run.

## Existing-arm screen

- completed A/B arms evaluated: 28
- core CAGR-first passes: 2
- both passes: Main `growth_confirmation` tilt05 and tilt10
- selected by frozen maximum-CAGR objective: `growth_confirmation_top_quintile_tilt10`
- forward return used in ranking: `false`
- original verdict: `reject_mdd_worse`
- new grid allowed: `false`

| Metric | Main baseline | tilt10 | Delta |
|---|---:|---:|---:|
| CAGR, cash-carry 25bps | 33.8057% | 35.7897% | +1.9839pp |
| MDD, diagnostic only | -25.3619% | -25.9265% | -0.5646pp |
| Sharpe | 1.2621 | 1.3225 | +0.0604 |
| OOS CAGR | 67.6737% | 70.2900% | +2.6163pp |
| OOS2 CAGR | 48.4972% | 52.2477% | +3.7505pp |

No Concentrated arm passed the frozen full/OOS/OOS2 CAGR direction gate.  The
nominal W4 SEC tilt increased full-period CAGR but remained negative in OOS and
OOS2, so changing the MDD objective did not reopen it.

## Fixed cost and cash-yield sensitivity

The exact existing baseline and tilt10 target books were replayed with integer
shares, next-close fills, lag <= 7, and no leverage.  All six relative CAGR
direction tests passed.

| Cash mode | Cost/side | Baseline CAGR | Candidate CAGR | dCAGR | Candidate MDD |
|---|---:|---:|---:|---:|---:|
| cash-carry | 25bps | 33.8057% | 35.7897% | +1.9839pp | -25.9265% |
| cash-carry | 50bps | 30.7966% | 32.6812% | +1.8847pp | -26.9310% |
| cash-carry | 100bps | 24.8364% | 26.5949% | +1.7585pp | -31.2349% |
| zero-yield | 25bps | 32.9404% | 34.9352% | +1.9949pp | -26.2276% |
| zero-yield | 50bps | 29.9448% | 31.8116% | +1.8668pp | -27.5518% |
| zero-yield | 100bps | 23.9422% | 25.7469% | +1.8047pp | -32.6843% |

The relative edge is not cash-interest dependent.  Absolute CAGR is highly
sensitive to trading cost, so 25bps results must not be presented without the
50/100bps context.

## Incremental P&L concentration

Reference scenario: cash-carry, 25bps per side.

- incremental ending equity: $86,331.35
- top ticker: MRVL, 22.07% of net incremental P&L — passes the 50% ticker gate
- top era: `2025_plus`, 59.59% — fails the 50% era gate
- attribution residual: $67.00, approximately 0.08% of incremental equity

| Era | Incremental P&L | Share of net increment |
|---|---:|---:|
| 2025_plus | $51,442.97 | 59.59% |
| 2023_2024_ai_bull | $31,463.50 | 36.45% |
| 2019_2021_pre_ai_bull | $5,231.06 | 6.06% |
| 2022_bear | -$1,806.19 | -2.09% |

The largest security contributors were MRVL 22.07%, PLTR 18.70%, WDC 14.40%,
UI 10.89%, and SMCI 9.85%.  The failure is therefore a regime concentration
problem, not a single-name concentration problem.

## Interpretation and stop rule

- Removing the -25% MDD gate reveals a real historical Main CAGR improvement.
- It does not produce a valid Concentrated challenger.
- The Main edge survives zero-yield and 100bps relative-cost tests.
- The edge is still too dependent on the most recent era and loses incremental
  P&L in the 2022 bear period.
- The exact arm remains in `do_not_repeat`; this review re-scored the completed
  result and did not authorize a new tilt percentage or threshold search.
- Because the frozen concentration gate failed, do not spend compute on the
  126-session embargo walk-forward and do not promote the arm.

Canonical target books, operating weights, cash, orders, production, and live
trading remain unchanged.  No fullrun was dispatched.

## Evidence

- `docs/run287_cagr_first_objective_contract_v1.json`
- `tools/audit_run287_cagr_first_objective.py`
- `tests/run287_cagr_first_objective_smoke.py`
- `outputs/run287_cagr_first_objective_audit_20260716/summary.json`
- `outputs/run287_cagr_first_objective_audit_20260716/sensitivity_results.csv`
- `outputs/run287_cagr_first_objective_audit_20260716/ticker_incremental_pnl.csv`
- `outputs/run287_cagr_first_objective_audit_20260716/era_incremental_pnl.csv`
- `outputs/run287_cagr_first_growth_confirmation_tilt10_sensitivity_20260716/`
