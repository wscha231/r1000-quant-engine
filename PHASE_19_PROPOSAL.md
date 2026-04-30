# Phase 19 — Portfolio Orchestrator (MANDATE_REGISTRY -> Unified Weight Map)

## Status
- **19a** (this commit) — Orchestrator scaffolding (additive, no behavior change)
- **19b** (future) — Replace 3 separate backtests with one orchestrator-driven sim

## Motivation

The 17v3 L2 commit added `MANDATE_REGISTRY` (main / concentrated /
tactical) but no engine code reads it. Currently we run 3 separate
backtests and report 3 separate metrics. A unified portfolio that
combines all 3 mandates per regime is the next architectural step.

Phase 19a builds the **scaffolding** — a pure transform function that
takes per-mandate weights and produces a unified target weight map.
Phase 19b will integrate this into a single walk-forward backtest.

## 19a — Schema

### Input

```python
main_weights:        dict[str, float]    {ticker: weight}, sum ~= 1.0 within mandate
concentrated_weights: dict[str, float]   {ticker: weight}, sum ~= 1.0 within mandate
tactical_weights:    dict[str, float]    {ticker: weight}, sum ~= 1.0 within mandate
regime_state:        str                 deep_bear / bear / neutral / bull / strong_bull
cfg:                 EngineConfig        (optional, for cap overrides)
```

### Output

```python
{
    "unified_weights": {ticker: weight},      # final target dict
    "cash_target": float,                     # residual (matches MANDATE_REGISTRY)
    "by_mandate_capacity": {                  # capacity actually used per mandate
        "main": float,
        "concentrated": float,
        "tactical": float,
    },
    "conflicts": [                            # tickers that appear in 2+ mandates
        {"ticker": str, "mandates": [str], "max_weight_used": float},
    ],
    "regime_state": str,
    "audit": {                                # for debugging + journal
        "input_weights_sum": {"main": ..., "concentrated": ..., "tactical": ...},
        "scaled_weights_sum": {...},
        "policy_capacity": {...},
    },
}
```

### Conflict resolution

If a ticker appears in multiple mandates, take the MAX weight after
mandate-capacity scaling. Conservative choice — avoids double-counting
exposure to the same name. Example:
```
main:         {AAPL: 0.05} after 0.75 main capacity scaling
concentrated: {AAPL: 0.20} after 0.10 conc capacity scaling -> 0.020 effective
unified:      {AAPL: 0.05}   (max wins)
conflicts:    [{ticker: AAPL, mandates: [main, concentrated], max_weight_used: 0.05}]
```

## 19a — Module Surface

`r1000_orchestrator.py` (new):

* `compose_unified_portfolio(main_w, conc_w, tact_w, regime_state, cfg=None) -> dict`
* `_scale_by_mandate_capacity(weights, mandate, regime_state) -> dict`
* `_merge_with_max(*weight_dicts) -> tuple[dict, list]`  (returns merged + conflicts)
* `audit_unified_portfolio(unified_dict, expected_total_capacity) -> dict`
  validation report (sum(weights) close to expected? cash within ε?)

`tools/run_orchestrator.py` (new): CLI for ad-hoc orchestration on
existing per-mandate output files (concentrated_holdings.csv +
backtest holdings.csv + tactical scanner output).

## 19a — Wire-in

NONE in 19a. The orchestrator is a passive utility producing
`outputs/orchestrator/unified_target_YYYY-MM-DD.json` from the most
recent per-mandate outputs. It does NOT replace existing backtest
logic.

## 19b roadmap (future)

1. Add `cfg.use_unified_orchestrator: bool = False` flag
2. New `backtest_unified_portfolio()` function in r1000_pipeline.py:
   * Walk-forward loop similar to `backtest_portfolio` but runs all 3
     mandate pickers per month + composes unified target
   * Single equity curve, single Sharpe/MaxDD/CAGR
3. Trade journal (Phase 18a) records mandate origin per pick
4. Verify: unified backtest CAGR >= max(main, concentrated) within
   noise band (else investigate orchestration bug)

## Ship gate (19a)

- Smoke 60+ tests pass
- Synthetic 3-mandate input produces correct unified weights with
  conflict detection
- Sum of unified weights matches expected total capacity per regime
- No regression in existing backtests (additive only)

## Engine-version

ENGINE_REUSE_VERSION NOT bumped. Pure scaffolding. Phase 19b will
require version bump when the unified backtest replaces existing
behavior.
