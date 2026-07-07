# Run287 Actual Results A/B And W4 Status

Date: 2026-07-07

Status: mixed research evidence; no hook or fullrun candidate yet.

## Guardrails

- No fullrun was dispatched.
- No policy hook was added.
- No threshold tuning was performed.
- No production promotion or live trading path is enabled.
- `period_forward_return` is not used by the broker A/B tool.
- `pit_universe_label_clean=false`; all evidence is research-only.
- The selected ticker set is preserved. The A/B only shifts weight among names
  already selected in the official run287 target book.

## Actual Results Broker A/B

Measurement contract:

- Source run: `28725350727`
- Signal: `actual_results_score`
- Metric mode: `broker_ledger_next_close_cash_carry`
- Replay end date: `2026-07-06`
- Cash rate: `DGS3MO`, 1 business-day lag, 50 bps haircut, ACT/365
- A/B arms:
  - `baseline`
  - `actual_results_top_quintile_tilt05`
  - `actual_results_top_quintile_tilt10`

| Portfolio | Arm | Verdict | CAGR | MaxDD | Delta CAGR pp | Delta MDD pp | OOS CAGR pp |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| Main | baseline | `baseline` | 34.25% | -25.36% | +0.00 | +0.00 | +0.00 |
| Main | actual_results_top_quintile_tilt05 | `reject_oos_cagr_worse` | 34.88% | -24.93% | +0.64 | +0.43 | -1.97 |
| Main | actual_results_top_quintile_tilt10 | `reject_oos_cagr_worse` | 35.45% | -24.59% | +1.20 | +0.77 | -4.06 |
| Concentrated | baseline | `baseline` | 48.66% | -22.96% | +0.00 | +0.00 | +0.00 |
| Concentrated | actual_results_top_quintile_tilt05 | `reject_oos_cagr_worse` | 48.28% | -23.19% | -0.38 | -0.24 | -4.41 |
| Concentrated | actual_results_top_quintile_tilt10 | `reject_mdd_worse` | 47.81% | -23.39% | -0.85 | -0.43 | -8.75 |

Interpretation:

- Main `actual_results_top_quintile_tilt10` restores the headline Main contract
  at 35.45% CAGR / -24.59% MDD.
- It is not accepted as a candidate because OOS CAGR worsens by 4.06 pp versus
  baseline. This is mixed evidence, not a clean pass.
- Concentrated is negative. Both actual-results tilts reduce CAGR and worsen
  OOS CAGR; the 10% tilt also worsens MDD.
- Allowed next action: rolling/OOS robustness review for Main tilt10 only.
- Disallowed next actions: hook, fullrun, threshold retuning, or production
  language.

## W4 External Feed Inventory

The local external artifact inventory found PIT SEC W4 sources:

| Feed | Rows | Tickers | Available From Max | Decision-time usable |
| --- | ---: | ---: | --- | --- |
| SEC Form4 transactions | 220,674 | 1,599 | 2026-05-19T10:03:54+00:00 | true |
| SEC 13F holdings | 1,798,508 | 3,351 | 2026-05-18T06:10:10+00:00 | true |

But the true earnings/guidance feed is still missing:

- `data_pit/events/earnings_revision_signals.parquet`: missing in this worktree
- `data_raw/events/earnings_revisions.csv`: previously documented missing

Interpretation:

- SEC Form4/13F can support W4 source-screen work.
- They do not substitute for true analyst revision or company guidance feed.
- W4 source-screen work is allowed; hook/fullrun remains blocked until source
  screen evidence passes and the user explicitly approves.

## Artifacts

- Actual-results combined summary:
  `outputs/run287_actual_results_broker_ab/summary.json`
- Main actual-results summary:
  `outputs/run287_actual_results_broker_ab/main/summary.json`
- Concentrated actual-results summary:
  `outputs/run287_actual_results_broker_ab/concentrated/summary.json`
- W4 external feed inventory:
  `outputs/run287_w4_external_feed_inventory/summary.json`
- Tools:
  - `tools/run_run287_profitability_broker_ab.py`
  - `tools/run_run287_w4_external_feed_inventory.py`
- Smokes:
  - `tests/run287_profitability_broker_ab_smoke.py`
  - `tests/run287_w4_external_feed_inventory_smoke.py`
