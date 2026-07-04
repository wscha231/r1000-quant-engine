# Clean-Control Main Top-N MDD Repair Check - 2026-07-04

## Status

This is a research-only fixed-book diagnostic. It does not justify a fullrun, production promotion, live trading, or a policy hook.

The goal was to test whether Main's remaining clean-control MaxDD failure can be repaired by reducing the long-tail of selected positions while preserving the official clean-control book, replay window, next-close fill model, 25 bps cost, integer shares, and cash-carry accounting.

## Inputs

- Source target book: `outputs/target_book_control_repro_root_cause/repro_a/official_main_target_book.csv`
- Transformation tool: `tools/run_main_top_n_concentration_filter.py`
- Replay tool: `tools/run_broker_ledger_replay.py`
- Price cache: `outputs/phase1_replay_goal_test/cache_prices`
- Cash rate source: `cache_macro/fred_dgs3mo_DGS3MO.parquet`
- Replay end: `2026-06-29`
- Fill mode: `next_close`
- Cost: `25 bps`
- Portfolio: `main`
- Metric mode: `broker_ledger_next_close_cash_carry`

## Results

| top N | CAGR | MaxDD | Sharpe | avg cash | trades | verdict |
| ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 8 | 27.97% | -18.49% | 1.284 | 46.87% | 1044 | `mdd_pass_cagr_short` |
| 10 | 29.70% | -20.70% | 1.247 | 39.32% | 1274 | `mdd_pass_cagr_short` |
| 12 | 32.54% | -22.53% | 1.262 | 33.09% | 1458 | `mdd_pass_cagr_short` |
| 13 | 33.37% | -24.05% | 1.258 | 30.45% | 1544 | `mdd_pass_cagr_short` |
| 14 | 34.77% | -24.86% | 1.274 | 28.05% | 1615 | `mdd_pass_cagr_short` |
| 15 | 36.06% | -25.81% | 1.292 | 26.61% | 1660 | `cagr_pass_mdd_short` |
| 18 | 36.06% | -25.81% | 1.292 | 26.61% | 1660 | `cagr_pass_mdd_short` |

## Interpretation

The Main clean-control book has a clear concentration boundary:

- `top15` / baseline passes CAGR but fails MaxDD: `36.06% / -25.81%`.
- `top14` repairs MaxDD but narrowly misses CAGR: `34.77% / -24.86%`.
- Tighter books repair MaxDD more comfortably, but destroy too much CAGR.

This is materially better than the previous broad Main MDD repair paths because the best boundary misses the CAGR target by only about `0.23pp`. However, it is still not a pass and must not be promoted as one.

The result suggests the remaining Main problem is not broad cash, broad stops, or broad event defense. It is a narrow boundary problem: the last tail position(s) provide enough upside to pass CAGR but enough stress exposure to fail MaxDD.

## Follow-Up

The next local step was executed immediately after this boundary check: a fixed-book AI Capex tilt on top of `top14`, using the same cash-carry and replay-end contract.

### Top14 + AI Capex Tilt Check

Tool update:

- `tools/run_ai_capex_tilt_broker_ab.py` now forwards cash-carry and replay-end parameters into `tools/run_broker_ledger_replay.py`.
- `tests/ai_capex_tilt_broker_ab_smoke.py` verifies those parameters are passed through.

Run:

- Target book: `outputs/clean_control_main_topn/top14/target_book.csv`
- Output: `outputs/clean_control_main_top14_ai_capex_tilt/main/`
- Metric mode: `broker_ledger_next_close_cash_carry`
- Replay end: `2026-06-29`

| arm | CAGR | MaxDD | Sharpe | dCAGR pp | dMDD pp | eligible events | verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| baseline top14 | 34.77% | -24.86% | 1.274 | +0.00 | +0.00 | 0 | `baseline` |
| AI bottleneck + momentum tilt15 | 35.36% | -24.76% | 1.283 | +0.58 | +0.10 | 344 | `research_pass_policy_candidate` |
| AI bottleneck + momentum + earnings tilt15 | 34.84% | -24.77% | 1.274 | +0.07 | +0.09 | 220 | `research_edge_too_small` |

This is the first clean-control Main fixed-book candidate in this track that clears both headline Main targets under the cash-carry accounting contract:

- CAGR `>= 35%`
- MaxDD `>= -25%`
- cap breach count `0`
- cash absolute delta sum `0`
- replay end matches `2026-06-29`

However, it is still research-only. It is not a fullrun trigger by itself because Concentrated remains separately gated and production remains blocked by PIT-universe evidence.

## Remaining Work Before Fullrun

Do not dispatch a fullrun from this Main result alone.

The next local steps are:

- `top14 + replacement-quality / rotation-quality` only if Main-specific fixed-book evidence exists.
- No broad gross floor, broad cash reduction, tight stop, or event-exit retry.
- Concentrated must still produce a clean-control candidate with CAGR `>= 50%` and MaxDD `>= -25%`.
- The prefullrun gate must be refreshed after the Main candidate and any Concentrated candidate are present.

Acceptance before any fullrun:

- Main CAGR `>= 35%`
- Main MaxDD `>= -25%`
- Metric mode remains `broker_ledger_next_close_cash_carry`
- Replay end remains `2026-06-29` or the current official validated end
- No broad cash reduction
- No production activation
- Concentrated path remains separately gated

## Current Verdict

`main_research_pass_candidate_fixed_book_cash_carry`

Top14 alone is the best discovered fixed-book Main MDD repair boundary. Top14 plus AI bottleneck momentum tilt15 becomes a Main research pass candidate under the current cash-carry/replay-end contract. It is not production evidence and not sufficient for a fullrun without a matching Concentrated candidate.
