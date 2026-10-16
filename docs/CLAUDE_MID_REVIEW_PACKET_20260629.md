# Claude Mid-Review Packet - AlphaOps vNext 2026-06-29

## Purpose

Ask Claude to review the latest AlphaOps vNext direction after the Main MDD
repair path was exhausted and the work shifted back to Concentrated CAGR.

This packet is a research-status handoff only.  It is not a production
promotion request.

## Current Governance

- Production promotion remains blocked while `pit_universe_label_clean=false`.
- No live trading.
- No fullrun unless a cheap broker-ledger A/B produces a real reason.
- No proxy 8Y/10Y work.
- Forward 63d/126d returns are audit labels only, never live ranking signals.
- User preference currently prioritizes CAGR improvement; long-only remains the
  working assumption and hedge work is not active.

## Recent PR/Work Summary

### PR #201 - Main MDD Negative Evidence

PR #201 was updated to reflect that the Main MDD cheap-repair path is exhausted.

Evidence:

- monthly cash/cap/stop variants failed to produce mission-quality tradeoff.
- intramonth event-defense failed.
- strict cash-only improved MDD slightly but damaged CAGR too much.
- event exits caused whipsaw and made both CAGR and MDD worse.

Interpretation:

- Do not continue small cash/stop/cap parameter tweaks for Main MDD.
- Main MDD is now a governance/risk-cap question unless the user reopens hedge
  or architecture redesign.

### Production Acceptance Contract

Added `docs/PRODUCTION_ACCEPTANCE_CONTRACT_20260629.md` on PR #201 branch.

Intent:

- separate canonical mission targets from interim operating gates.
- keep canonical mission visible:
  - Main CAGR >= 35%, MDD >= -25%.
  - Concentrated CAGR >= 50%, MDD >= -25%.
- document that MDD may need governance treatment as a risk cap, not silent
  target rewrite.

### PR #202 - Actual-Results Hold Screen

Created draft PR #202:

- `tools/run_actual_results_hold_screen.py`
- `tests/actual_results_hold_screen_smoke.py`
- small extension to hold-duration drop rows for actual/revision/event fields.

Clean7Y Concentrated screen result on `artifacts/28074476465/outputs`:

- primary predicate: `actual_results_positive_pit_hold`
- Full: 52 rows, positive rate 53.85%, mean 126d excess +10.39%.
- IS: 40 rows, positive rate 55.00%, mean +10.87%.
- OOS: 12 rows, positive rate 50.00%, mean +8.80%.
- screen verdict: `screen_pass=true`

Important: this was only a forward-label screen, not broker evidence.

### Follow-Up Hook Test From PR #202 - Rejected

I tested the direct default-OFF policy action implied by #202:

- Concentrated-only.
- prior holding must be healthy (`HOLD`, prior keep, >=2% prior weight).
- leader tier must be `DUAL_LEADER` or `SECTOR_LEADER`.
- 3m/6m benchmark RS must be positive.
- `price_above_ma200 >= 0.5`.
- `actual_results_score > 0`.
- hook raises replacement threshold.

Cheap target-book screen:

- `0.75 sigma`: replacement tests fired, but target book was identical to
  baseline. No broker A/B justified.
- `1.10 sigma`: target book changed materially:
  - 29 rebalance dates changed.
  - 134 changed weight rows.
  - total absolute weight delta 9.21.

Broker-ledger A/B for `1.10 sigma`, same generated target-book substrate:

| Arm | CAGR | MDD | Sharpe | OOS CAGR | OOS MDD | Trades | Fees |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline | 46.14% | -28.37% | 1.271 | 112.93% | -28.37% | 577 | $48.0k |
| actual-results hold 1.10 sigma | 45.09% | -27.50% | 1.258 | 112.43% | -27.50% | 563 | $45.2k |

Delta:

- CAGR: -1.05pp.
- MDD: +0.87pp.
- Sharpe: -0.013.

Decision:

- reject direct broad actual-results replacement-threshold hook.
- it reduces churn and improves MDD, but sacrifices Concentrated CAGR.
- this is the wrong policy action for the active Concentrated CAGR gap.

### PR #203 - Whipsaw Cost Audit

Created draft PR #203:

- `tools/run_whipsaw_cost_audit.py`
- `tools/run_whipsaw_pit_feature_screen.py`
- `tests/whipsaw_cost_audit_smoke.py`
- `tests/whipsaw_pit_feature_screen_smoke.py`
- registered in `tools/run_pr_validation.py`

Purpose:

- quantify same-ticker sell-then-rebuy events from broker-ledger trades.
- answer the user's qualitative concern: "the system finds leaders, sells them,
  then buys them back much higher."
- classify those events using only PIT-visible sell-time target-book features
  before designing any policy hook.

Clean7Y Concentrated result on `artifacts/28074476465/outputs`:

- event_count: 85 sell->rebuy events within 252 days.
- positive_whipsaw_count: 77.
- positive_whipsaw_rate: 90.59%.
- mean price return while out: +26.39%.
- median price return while out: +19.84%.
- total missed reentry cost: $549.2k.
- total avoided loss: $5.7k.
- net whipsaw cost: $543.5k.
- net whipsaw cost / ending equity: 37.20%.

Top missed-cost tickers:

| Ticker | Events | Missed Cost | Mean Return While Out |
|---|---:|---:|---:|
| WDC | 5 | $154.4k | +42.37% |
| CIEN | 4 | $65.6k | +36.21% |
| TSLA | 8 | $59.1k | +40.97% |
| SNDK | 1 | $49.4k | +71.35% |
| CORT | 2 | $26.1k | +38.10% |

Interpretation:

- Whipsaw/re-entry is material and better aligned with the user's diagnosis than
  broad hold-threshold logic.
- The next candidate should not be a blanket hold extension.
- It should be a narrow PIT-only rule that prevents repeated sell/rebuy of the
  same leader when thesis remains intact.

### PR #203 Follow-Up - Whipsaw PIT Feature Screen

I added a second research-only screen on the same PR:

- joins each whipsaw event to the latest Concentrated target-book row at or
  before the sell signal date.
- separates full exits from partial sells.
- reports generic sell-time PIT predicates; forward re-buy outcomes remain
  audit labels only.

Run:

`tools/run_whipsaw_pit_feature_screen.py --latest-run artifacts/28074476465/outputs --portfolio concentrated --output-dir artifacts/28074476465/whipsaw_pit_feature_screen_20260629`

Join quality:

- whipsaw events: 85.
- PIT-joined events: 85.
- target book used:
  `artifacts/28074476465/outputs/alphaops_vnext/official_concentrated_target_book.csv`.

Key predicate results:

| Predicate | Events | Positive Rate | Net Cost | OOS Events | OOS Net Cost |
|---|---:|---:|---:|---:|---:|
| all_events | 85 | 90.59% | $543.5k | 29 | $363.9k |
| full_exit | 28 | 92.86% | $171.0k | 7 | $82.7k |
| partial_sell | 57 | 89.47% | $372.5k | 22 | $281.2k |
| thesis_intact_actual_results | 43 | 90.70% | $237.8k | 15 | $187.6k |
| partial_sell_thesis_intact_actual | 36 | 91.67% | $214.6k | 14 | $177.9k |
| full_exit_thesis_intact_actual | 7 | 85.71% | $23.2k | 1 | $9.7k |
| actual_results_positive | 52 | 92.31% | $279.2k | 18 | $214.0k |
| revision_positive | 67 | 91.04% | $417.3k | 23 | $278.2k |

Screen verdict:

- `screen_pass_design_default_off_whipsaw_hook`.
- primary predicate: `thesis_intact_actual_results`.

Interpretation:

- The full-exit-only subset is too thin for a first policy hook
  (`full_exit_thesis_intact_actual`: 7 events, OOS 1).
- Most dollar leakage is partial-sale whipsaw, especially WDC/CIEN/NVDA/SHOP
  style repeated reductions and later rebuys.
- A hook that only blocks full exits would miss most of the measurable cost.
- The better next candidate is a staged-sell / sell-throttle rule:
  when thesis is intact by sell-time PIT evidence, reduce less aggressively
  instead of raising all replacement thresholds.
- This directly addresses why the earlier actual-results threshold hook failed:
  it globally blocked rotation and reduced CAGR, while the whipsaw candidate
  targets only sell pressure in names that the system later had to buy back.

## Current Working Diagnosis

The system often identifies future leaders correctly.  The larger leak is not
pure stock selection.  The leak is execution timing around exits, replacement,
and later re-entry into the same names.

However, the direct "raise replacement gap for actual-results leaders" action
failed because it also blocked useful rotation and reduced CAGR.

Therefore the next hypothesis should target whipsaw specifically, not all
healthy leaders.  The PIT screen now suggests the most material leak is not
full liquidation alone; it is repeated partial reduction of still-intact leaders
followed by higher-price re-entry.

## Proposed Next Candidate

Design a default-OFF, PIT-only "same-name whipsaw guard" hook candidate, but keep
it scoped to sell pressure and staged reduction.  Do not implement another broad
replacement-threshold raise.

Possible research predicate:

- ticker was held recently and sold or dropped.
- candidate remains PIT-visible and thesis-intact:
  - positive 3m/6m RS.
  - above MA200.
  - actual_results_score > 0 or revision/event confirmation positive.
  - no hard reject, no MA200 break, no negative guidance/thesis break.
- same ticker reappears as a valid candidate within a cooldown window.
- action should prefer retention or staged reduction instead of full exit.

The screen has now passed on historical whipsaw labels, but the next hook must
still be default-OFF and broker-tested.  Do not hardcode WDC, CIEN, SNDK, TSLA,
AI, memory, or any date.

## Questions For Claude

1. Is PR #203 merge-safe as a research-only diagnostic?
2. Is the PIT feature screen leakage-safe enough for policy design?  It joins
   sell-date target-book features and uses re-buy outcome only as an audit label.
3. Should the first hook target partial-sell throttling, full-exit prevention,
   or re-entry acceleration?  The current evidence favors partial-sell
   throttling because full-exit thesis-intact evidence is too thin.
4. Is `thesis_intact_actual_results` too broad, or should it be narrowed to
   `partial_sell_thesis_intact_actual` for the first hook?
5. Given the rejected actual-results threshold hook, should the hook modify
   target weight reduction size rather than replacement threshold?
6. Is the whipsaw net cost large enough to prioritize this above other
   Concentrated CAGR levers?
7. Any leakage risks in the current audit?  The audit uses realized re-buy paths
   as labels only; future policy must be designed forward-blind and then
   broker-tested.

## Recommended Immediate Next Step

Merge #203 if review agrees it is safe.  Then implement exactly one default-OFF
whipsaw sell-throttle hook candidate:

- Concentrated only.
- PIT predicate based on sell-date thesis integrity.
- reduce less aggressively / stage reductions for intact leaders.
- do not globally raise replacement thresholds.
- do not hardcode tickers, themes, eras, or dates.

The hook must then be tested with:

- applied_count > 0,
- target-book delta,
- broker-ledger delta,
- OOS non-collapse,
- no fullrun until cheap broker A/B passes.
