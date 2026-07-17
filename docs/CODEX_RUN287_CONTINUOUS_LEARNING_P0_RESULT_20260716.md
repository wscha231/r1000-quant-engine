# Run287 Continuous Learning P0 Result — 2026-07-16

## Outcome

The first continuous-learning PR scope is implemented locally as a review-only, append-only causal ledger. It joins the frozen current decision frame, six-head score stack, published score/rank, advisory selector, operating target books, and simulated fill ledger without changing any of them.

This work does **not** improve the canonical CAGR/MDD by itself. It creates the measurement layer required to identify whether future leakage comes from selection, entry timing, hold/exit, sizing/cash, or execution before opening one challenger.

## Implemented scope

- `docs/run287_continuous_learning_contract_v1.json`
- `tools/build_run287_decision_outcome_ledger.py`
- `tools/audit_run287_policy_attribution.py`
- `tools/audit_run287_model_health.py`
- `tests/run287_decision_outcome_ledger_smoke.py`
- `tests/run287_policy_attribution_smoke.py`

The two smoke tests are also registered in `tools/run_pr_validation.py`.

## Actual exact-close validation

Source decision date: `2026-07-13` close. The output root is:

`outputs/run287_decision_outcome_ledger_20260716_close_20260713/`

| Gate | Result |
|---|---:|
| Unique tickers | 989 / 989 |
| Decision events | 2,967 = 989 × 3 selector scenarios |
| Raw/scaled model features | 238 / 238 |
| Prediction heads | 6 / 6 |
| Future feature rows | 0 |
| Missing selected/rejected reason | 0 |
| Duplicate primary keys | 0 |
| Operating-share mismatches | 0 |
| Paper cash reconciliation | within $0.01 |
| Same-date rerun | 2,967 semantic duplicates, 0 appended |
| Decision event log SHA-256 before/after rerun | identical (`0c935fa6...a877cb0e`) |
| Target/order/cash/model/selector mutation | 0 |

Ledger status: `READY_RUN287_DECISION_OUTCOME_LEDGER_REVIEW_ONLY`.

## Current forward verdict

- Policy attribution: `UNDERPOWERED_POLICY_ATTRIBUTION_WAITING_63D`
- Model health: `UNDERPOWERED_MODEL_HEALTH_HISTORY`
- Completed 63-session outcome rows: 0
- Observed decision dates in the new all-universe ledger: 1
- Automatic retraining: forbidden
- Automatic champion promotion: forbidden
- PIT universe label clean: false

The underpowered verdict is expected. No return was backfilled into a historical date, and missing outcomes remain pending rather than being dropped or treated as failure/success.

## Attribution contract

- Selection controls are fixed from the same decision date, prefer the same sector, then use nearest published rank, log market cap, and 252-day volatility without replacement.
- Matching never reads the future outcome when choosing a control.
- Entry timing remains unidentified until the alternate entry path is observed; it is not inferred from the best realized delay.
- Hold/exit and sizing/cash reports are explicitly descriptive until a fixed counterfactual or preregistered A/B exists.
- Execution reconciliation is available immediately and remains separate from investment alpha.

## Next gate

Run the ledger after each completed-close decision/selector/operating/paper cycle and resolve 1/5/21/63/126/252-session outcomes from the bounded price cache. Do not open a model or policy challenger until the contract's forward gates mature: at least 26 distinct decision weeks, 200 resolved 63-session observations, and 50 distinct tickers, followed by the fixed-control and block-bootstrap review.

No fullrun, historical endpoint change, threshold grid, production activation, live trading, or target-book write is authorized by this result.

## 2026-07-16 outcome-resolution addendum

- The daily orchestration wrapper now discovers the exact packet inputs, appends decisions/outcomes, runs attribution/model-health audits, and produces a rotating bounded price queue.
- The first bounded queue resolved 888 one-session outcome events while preserving all 2,967 decision events.
- The real selector summary uses `cash_weight`; the producer now accepts that canonical field as well as the legacy `advisory_cash_weight` alias.
- The corrected immutable replay is `outputs/run287_decision_outcome_ledger_20260716_close_20260713_v2/`. The earlier local ledger remains preserved.
- Correct advisory cash is 8.60% Main strict, 7.59% Main prior-hold bridge, and 34.09% Concentrated strict.
- Primary 63-session attribution and model-health gates remain underpowered.
