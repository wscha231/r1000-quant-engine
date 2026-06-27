# Score-Sizing Closeout - 2026-06-27

## Verdict

The Concentrated score-sizing work is closed as **research-only infrastructure**.
The cap-safe policy candidate failed the broker-ledger A/B gate, so this lever
does **not** justify a data refresh, full rebuild, production activation, or
promotion claim.

## What Landed

- PR #190: sizing signal screen.
- PR #191: concentrated sizing audit-label cheap screen.
- PR #192: default-OFF Concentrated score-sizing hook.
- PR #193: broker-ledger A/B harness for score-sizing arms.

All production-facing behavior remains unchanged unless the explicit
Concentrated sizing env flag is enabled. The hook is parked as default-OFF
research infrastructure.

## Broker A/B Result

Source artifact:

- `artifacts/28074476465/outputs`
- `artifacts/28074476465/cache_prices`
- `artifacts/28074476465/concentrated_score_sizing_broker_ab`

Baseline:

- CAGR: 47.20%
- MDD: -25.82%
- Sharpe: 1.440
- max weight: 30.00%
- cap breaches: 0

Arms:

| Arm | Delta CAGR | Delta MDD | Cap breaches | Verdict |
| --- | ---: | ---: | ---: | --- |
| `blend75_rank_power1_5_uncapped` | +0.26pp | +0.06pp | 30 | `research_pass_uncapped_only` |
| `blend75_rank_power1_5_cap30` | -0.76pp | -0.12pp | 0 | `reject_no_cagr_edge` |
| `blend50_rank_power1_5_cap30` | -0.25pp | +0.48pp | 0 | `reject_no_cagr_edge` |

Interpretation:

- The uncapped arm contains alpha evidence, but it violates the 30% single-name
  cap and is not a policy candidate.
- Cap-safe score sizing did not improve CAGR and therefore fails the research
  pass gate.
- No fullrun should be dispatched from this lever.

## Governance

- `production_promotion_allowed=false`.
- `pit_universe_label_clean=false` remains a production blocker.
- Partial-year 2026 annualized CAGR is not used as proof.
- No live trading or production mutation is allowed from this result.

## Follow-up

Before future A/Bs, keep the new baseline reproducibility audit in the loop:

- target-book path and sha256,
- price-cache manifest start/end,
- official metrics vs A/B baseline window,
- broker metric mode,
- target-book source and row/date counts.

This is required because the official clean-7Y result and the local A/B baseline
can differ slightly when the local price cache extends beyond the official run
end date. That drift must be explained, but it does not change this lever's
decision: cap-safe score sizing is rejected.

## Next Priority

The next Concentrated CAGR lever should be a **green/bull gross-exposure floor**
cheap broker sweep, not another score-sizing fullrun. It must preserve
WATCH/DEFENSE/CRISIS cash defense and prove the effect on broker-ledger
metrics before any full rebuild.
