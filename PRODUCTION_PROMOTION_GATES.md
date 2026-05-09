# Production Promotion Gates

This document defines how research/proxy results and AutoLearning proposals can
be promoted toward live or paper trading. It is intentionally stricter than
weight-level backtest reporting.

## Evidence Ladder

1. **Proposal**
   - AutoLearning or a sidecar writes a policy hypothesis.
   - No production default changes.
   - No broker order generation beyond preview files.

2. **Research Replay**
   - Historical monthly or proxy replay shows whether the idea is worth further
     work.
   - These artifacts must be marked `valid_for_production=false`.
   - Examples: monthly hard-stop proxy, lifecycle review proxy, discovery-only
     theme concentration.

3. **Account-Compatible Replay**
   - Candidate is replayed through broker-ledger assumptions:
     - next-close fills after observable signals;
     - integer shares;
     - cash ledger;
     - no leverage unless explicitly tested;
     - transaction costs;
     - no forward-return labels for trade timing.
   - Candidate metrics may be `valid_for_production=true` only at this stage.

4. **Shadow**
   - Candidate runs after every market close and writes order previews.
   - Orders are not sent to a broker.
   - Shadow results are compared against the official account evaluation.

5. **Canary**
   - Small capital or paper-broker allocation.
   - Requires explicit human approval.
   - Daily reconciliation must pass.

6. **Production**
   - Active policy is allowed to influence target portfolios and order previews.
   - Broker API execution remains a separate approval gate.

## Numeric Gates

Main portfolio production promotion requires all of:

- `valid_for_production=true`
- `metric_mode` starts with `broker_ledger`
- CAGR >= 30%
- MaxDD >= -15%
- Sharpe >= 1.20
- no invalid target-weight periods
- 25 bps cost case passes target gates
- 50 bps cost case does not materially break the thesis
- no feature leakage audit failures
- stress-window review passes
- human approval

Concentrated portfolio production promotion requires all of:

- `valid_for_production=true`
- `metric_mode` starts with `broker_ledger`
- CAGR >= 50%
- MaxDD >= -18%
- Sharpe >= 1.25
- no invalid target-weight periods
- explicit single-name cap policy review
- hard-stop / distribution-exit logic validated on daily prices
- 25 bps cost case passes target gates
- 50 bps and 75 bps cost cases remain understandable
- no feature leakage audit failures
- stress-window review passes
- human approval

## AutoLearning Activation Rule

AutoLearning remains proposal-only until its candidate policy creates an
account-compatible replay candidate that passes the relevant numeric gate.

After a pass:

1. write a shadow policy file;
2. run at least one fresh full rebuild or replay from current artifacts;
3. compare `outputs/account_evaluation/*` and `outputs/portfolio_goal_search/*`;
4. require human approval;
5. only then allow production policy wiring.

The engine must never promote a proxy-only result directly to production.
