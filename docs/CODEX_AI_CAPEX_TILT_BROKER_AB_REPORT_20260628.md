# AI Capex Tilt Broker A/B Report — 2026-06-28

## Scope

This report records the cheap broker-ledger A/B that follows the AI Capex bottleneck screen.

It is not a fullrun and not production promotion. It reuses the clean7Y target books and price cache under:

- `artifacts/28074476465/outputs/alphaops_vnext/`
- `artifacts/28074476465/cache_prices/`

The tested arms preserve the selected ticker set. They only shift existing target weights inside the same rebalance date.

## Tested Arms

1. `baseline`
2. `ai_bottleneck_momentum_tilt15`
   - existing selected rows only
   - requires AI Capex bucket
   - requires bottleneck score high
   - requires momentum high
   - does not require earnings confirmation
3. `ai_bottleneck_momentum_earnings_tilt15`
   - same as above
   - additionally requires earnings confirmation
   - current artifact has no true vendor EPS/guidance feed, so this mostly uses `actual_results_score_fallback`

All arms:

- broker replay mode: `broker_ledger_next_close`
- integer shares
- 25 bps per side
- max fill lag 7 days
- no selected ticker additions
- no cash target change when caps are feasible
- no production mutation

## Concentrated Result

| Arm | Verdict | CAGR | MDD | Sharpe | ΔCAGR pp | ΔMDD pp | OOS ΔCAGR pp |
|---|---|---:|---:|---:|---:|---:|---:|
| baseline | baseline | 47.20% | -25.82% | 1.440 | +0.00 | +0.00 | +0.00 |
| AI bottleneck + momentum | reject_oos_cagr_worse | 46.82% | -25.94% | 1.431 | -0.37 | -0.12 | -0.65 |
| AI bottleneck + momentum + earnings fallback | reject_oos_cagr_worse | 46.12% | -25.82% | 1.420 | -1.08 | -0.00 | -4.36 |

Interpretation:

- Reject for Concentrated.
- The cheap forward-label screen did not survive broker-ledger A/B.
- This does not close the Concentrated 50% CAGR target gap.
- Do not implement a Concentrated AI Capex tilt hook from this evidence.

## Main Result

| Arm | Verdict | CAGR | MDD | Sharpe | ΔCAGR pp | ΔMDD pp | OOS ΔCAGR pp |
|---|---|---:|---:|---:|---:|---:|---:|
| baseline | baseline | 33.93% | -26.02% | 1.239 | +0.00 | +0.00 | +0.00 |
| AI bottleneck + momentum | research_pass_policy_candidate | 34.58% | -25.93% | 1.251 | +0.65 | +0.09 | +1.74 |
| AI bottleneck + momentum + earnings fallback | reject_oos_cagr_worse | 33.93% | -26.00% | 1.237 | +0.00 | +0.02 | -0.32 |

Interpretation:

- Main-only AI bottleneck + momentum tilt passes this cheap broker A/B.
- It improves CAGR by +0.65pp and improves MDD by +0.09pp on the same broker-ledger replay setup.
- OOS CAGR also improves by +1.74pp.
- The earnings-confirmed fallback variant should be rejected because OOS CAGR is worse.

## Important Caveats

This is a cheap broker A/B, not the final official fullrun.

The absolute baseline values differ from earlier official summaries because this replay uses the local artifact price cache and target books available in this workspace, ending 2026-06-25. The decision should rely on deltas inside the same replay setup.

Production promotion remains blocked by normal evidence gates, including PIT universe membership.

## Decision

Proceed only with a Main default-OFF candidate:

`PHASE_AI_CAPEX_MOMENTUM_TILT_ENABLED`

Initial policy constraints:

- Main portfolio only
- default OFF
- preserve selected ticker set until a full policy replay proves otherwise
- no effect on Concentrated
- no earnings-confirmation requirement until true EPS/guidance feed exists
- no fullrun until a target-book screen shows `applied_count > 0` and no unexpected target/cash mutation

Do not implement:

- Concentrated AI Capex tilt
- earnings-confirmation mandatory version based on `actual_results_score_fallback`
- production activation

## Next Step

Implement a default-OFF Main-only policy hook that mirrors the passing arm:

- AI Capex bucket
- bottleneck high
- momentum high
- no earnings confirmation requirement

Then run a cheap target-book screen to verify:

- `applied_count > 0`
- Main target weights change only where intended
- cash is unchanged
- Concentrated is unchanged

Only after that should broker A/B be rerun through the policy path.

## Follow-Up Implementation: Main Default-OFF Hook

Implemented:

`PHASE_AI_CAPEX_MOMENTUM_TILT_ENABLED`

Code path:

- `tools/run_alphaops_vnext_policy_replay.py::apply_main_ai_capex_momentum_tilt`
- called after the existing Main risk/cap overlays
- before output rows are written

Rules:

- Main only
- Concentrated always no-op
- default OFF returns the original records unchanged
- existing selected tickers only
- stock gross preserved
- cash unchanged
- no earnings confirmation requirement
- no production activation

Telemetry:

- `pre_main_ai_capex_momentum_tilt_weight`
- `main_ai_capex_momentum_tilt_weight`
- `main_ai_capex_momentum_tilt_delta`
- `main_ai_capex_momentum_tilt_enabled`
- `main_ai_capex_momentum_tilt_applied`
- `main_ai_capex_momentum_tilt_strength`
- `ai_capex_value_chain_bucket`
- `ai_capex_bottleneck_score`

Fast applied screen:

`tools/run_ai_capex_momentum_tilt_applied_screen.py`

Clean7Y target-book application:

| Portfolio | Status | Dates | Applied events | Changed dates | Total abs weight delta | Cash unchanged | Ticker set preserved |
|---|---|---:|---:|---:|---:|---|---|
| Main | `screen_pass_applied` | 85 | 360 | 81 | 3.2497 | true | true |
| Concentrated | `blocked_no_applied_events` | 85 | 0 | 0 | 0.0000 | true | true |

Interpretation:

- The hook is not a no-op for Main.
- The hook is a deliberate no-op for Concentrated, matching the broker A/B rejection.
- A full policy replay or fullrun is still not justified until this target-book path is reviewed and accepted.

Validation:

- `tests/ai_capex_momentum_tilt_hook_smoke.py`
- `tests/ai_capex_momentum_tilt_applied_screen_smoke.py`
- `tools/run_pr_validation.py --only ai_capex --only alphaops_vnext_policy_replay`

## Follow-Up Broker Replay: Hook-Generated Target Book

After the applied-count screen passed, the hook-generated Main target book was
sent through `tools/run_broker_ledger_replay.py` with the same clean7Y artifact
price cache and next-close broker settings.

Inputs:

- baseline target book: `artifacts/28074476465/outputs/alphaops_vnext/official_main_target_book.csv`
- tilt target book: `artifacts/28074476465/ai_capex_momentum_tilt_applied_screen_20260628/main/tilted_target_book.csv`
- price cache: `artifacts/28074476465/cache_prices`
- broker mode: `broker_ledger_next_close`, integer shares, 25bps per side, max fill lag 7
- OOS split: `2024-06-03`
- OOS2 split: `2023-06-03`

Result:

| Metric | Baseline | Main AI Capex tilt | Delta |
|---|---:|---:|---:|
| CAGR | 33.93% | 34.91% | +0.98pp |
| MaxDD | -26.02% | -26.04% | -0.03pp |
| Sharpe | 1.239 | 1.257 | +0.018 |
| Years | 7.061 | 7.061 | 0.000 |
| Avg cash | 26.69% | 26.70% | +0.01pp |
| Trades | 1693 | 1694 | +1 |
| Fees | $37,986 | $38,545 | +$559 |
| Gross traded | $15.19M | $15.42M | +$0.22M |

OOS checks:

| Window | Baseline CAGR | Tilt CAGR | Delta | Baseline MaxDD | Tilt MaxDD | Delta |
|---|---:|---:|---:|---:|---:|---:|
| OOS 2024-06-03+ | 71.88% | 73.59% | +1.71pp | -24.31% | -24.28% | +0.03pp |
| OOS2 2023-06-03+ | 58.04% | 59.82% | +1.78pp | -24.31% | -24.28% | +0.03pp |

Verdict:

- `research_pass_main_cagr_candidate`
- The hook clears the CAGR-improvement bar for Main on the broker ledger.
- OOS and OOS2 do not collapse.
- Full-window MDD is effectively flat but still slightly worse, and the
  absolute Main MDD target remains failed.
- Main target remains below the 35% CAGR mission target by about 0.09pp.
- This is not a production candidate and does not justify a fullrun by itself.

Next gate:

- Review this as a Main CAGR lever only.
- Pairing it with a separate Main MDD repair lever is still required before any
  mission-target claim.
- Do not apply it to Concentrated; the Concentrated AI Capex tilt was rejected
  by the previous broker A/B.
