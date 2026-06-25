# AlphaOps vNext Layer Decision Ledger - 2026-06-25

This ledger freezes the current evidence after merging the ChatGPT Pro and
Claude review guidance. It separates official full-run evidence from local
target-book screens so future work does not promote a layer from the wrong
measurement mode.

## Non-Negotiable Evidence Rules

- Primary strategy performance must be read from `broker_ledger_next_close`.
- Daily risk overlays must be labelled separately as
  `broker_ledger_position_risk_next_close`.
- Proxy, weight-level, forward-return, and overlay-only metrics are screening or
  audit evidence only.
- Forward returns may be written as audit labels, but must not affect ranking,
  target books, cash policy, or live signals.
- `pit_universe_label_clean=false` continues to block production promotion.
- No layer below is a live-trading or production-promotion approval.

## Authoritative Baseline

Source: run `28074476465`, official broker-ledger artifact.

| Portfolio | Metric mode | CAGR | MaxDD | Sharpe | Years | Status |
|---|---:|---:|---:|---:|---:|---|
| Main | broker_ledger_next_close | 33.15% | -26.02% | 1.219 | 7.055 | research only |
| Concentrated | broker_ledger_next_close | 46.24% | -25.82% | 1.421 | 7.055 | research only |

Production remains blocked because the evidence contract is not PIT-universe
clean enough. The 7Y window is useful for research and A/B, not automatic
promotion.

## Layer Decisions

### Keep As Measurement / Plumbing

| PR | Layer | Decision | Reason |
|---:|---|---|---|
| #167 | Position-risk official baseline fallback | Keep, merge candidate | Prevents risk-grid screens from comparing against a zero or blocked baseline when official broker metrics live in `account_evaluation/official_metrics.json`. |
| #169 | Stock-selection forward audit labels | Keep, merge candidate | Adds review-only `forward_21d/63d/126d_excess` labels with `used_forward_return_in_ranking=false`; needed to identify missed-leader leaks without live lookahead. |

### Keep As Small Research Levers

| PR | Layer | Local broker-screen result | Decision |
|---:|---|---|---|
| #166 | Earnings revision break warning | Concentrated +0.22pp CAGR, -0.027pp MaxDD worse, Sharpe +0.006 | Keep default-OFF. Useful small component, not a standalone target fix. |
| #170 | Dynamic leader candidate rescue | Main-only replacement-gap credit +0.23pp CAGR, unchanged MaxDD, Sharpe +0.005 | Keep default-OFF and Main-scoped. Broad score bonus was rejected. |

### Keep As Main MDD Candidate, Not Production

Official artifact Main target book with daily trailing-stop overlay:

| Trailing stop | Metric mode | CAGR | Delta CAGR | MaxDD | Delta MaxDD | Sharpe | Risk exits | Decision |
|---:|---|---:|---:|---:|---:|---:|---:|---|
| Baseline | broker_ledger_next_close | 33.15% | - | -26.02% | - | 1.219 | - | Baseline |
| -25% | broker_ledger_position_risk_next_close | 34.26% | +1.11pp | -26.46% | -0.45pp | 1.277 | 11 | Reject: MDD worse |
| -30% | broker_ledger_position_risk_next_close | 34.46% | +1.31pp | -24.34% | +1.68pp | 1.271 | 6 | Main MDD repair candidate |
| -35% | broker_ledger_position_risk_next_close | 34.85% | +1.70pp | -25.01% | +1.01pp | 1.279 | 2 | Near-target, but thin exit evidence and slightly misses MDD |
| -45% | broker_ledger_position_risk_next_close | 34.62% | +1.47pp | -25.70% | +0.32pp | 1.269 | 1 | Reject: MDD still fails |

Interpretation:

- `-30%` is the cleanest Main drawdown repair screen.
- `-35%` has better CAGR but only two exits and still does not clearly pass the
  -25% MDD gate on official artifact evidence.
- This is a daily risk overlay candidate, not a primary monthly target-book
  promotion.

### Reject / Do Not Recycle As-Is

| Layer | Evidence | Decision |
|---|---|---|
| Broad gross-floor / cash reduction | Concentrated floor 0.60-0.75 lowered CAGR to about 38.5-38.6% and worsened MaxDD to about -36.5%. | Reject. The cash was not idle in this implementation; broad exposure increase destroys drawdown. |
| Broad dynamic-leader score bonus | Main CAGR -0.61pp and MaxDD -1.82pp worse; Concentrated CAGR -4.35pp despite MDD improvement. | Reject. Keep only the narrower replacement-gap idea. |
| PR166 + PR170 combined screen | Main CAGR improved locally, but Main MaxDD stayed around -26%; Concentrated only +0.22pp. | Do not create combo PR. Merge and test independently. |
| Concentrated weak-only rescue local patch | Changed telemetry/rows but broker metrics were exactly unchanged. | Reject as no-op. |
| Shakeout guard as alpha lever | Plumbing is safe, but screens showed no material broker delta/no effective suppression. | Keep draft/plumbing only; not a priority alpha lever. |

## Current Ready Merge Candidates

Ready, mergeable, CI green:

1. PR #167 - measurement correctness for position-risk baseline fallback.
2. PR #169 - missed-leader forward audit labels.
3. PR #166 - default-OFF earnings revision break warning.
4. PR #170 - default-OFF Main-only dynamic leader replacement-gap credit.

Recommended merge order:

1. #167 and #169 first, because they improve measurement quality.
2. #166 and #170 next, because they are default-OFF research levers.
3. Keep #168 draft unless a new screen proves SHAKEOUT actually changes
   broker-ledger behavior.

## Next Work Order

### Main

1. Treat `daily trailing -30%` as the current Main MDD repair candidate.
2. Re-run through the official sidecar path after #167 is merged, ensuring:
   - baseline source is not zero or blocked,
   - `risk_exit_count > 0`,
   - `metric_mode=broker_ledger_position_risk_next_close`,
   - report remains review-only.
3. Do not combine with PR #170 until the interaction is explicitly measured,
   because the combo screen failed to keep Main MaxDD inside -25%.

### Concentrated

1. Do not use gross-floor/cash reduction as the next lever.
2. Use #169 labels to isolate high-value `cap_or_replacement` misses.
3. Design the next Concentrated lever as selective leader capture:
   - allow only PIT-visible high-conviction new leaders,
   - do not replace intact DUAL/SECTOR leaders,
   - require applied-count telemetry,
   - reject if broker-ledger CAGR does not improve without worsening MaxDD.

## Current State Summary

- The system is no longer missing one large obvious toggle.
- Main needs a risk overlay plus separate CAGR recovery.
- Concentrated needs better leader capture, not more gross exposure.
- The most important infrastructure now is accurate measurement: baseline
  fallback, forward audit labels, and strict separation of official target-book
  metrics from daily risk-overlay metrics.

