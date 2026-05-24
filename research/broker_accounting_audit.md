# A1/A2 Broker Accounting Audit

- Audited: **2026-05-24**
- Base dir: `/home/user/r1000-quant-engine`

## Gates

### A1 -- delisted_cost_basis_fallback_eliminated
- verdict: _inconclusive_
- status: `no_membership_data`
- delisted candidates: 0, with exit price: 0, without: 0

### A2 -- survivorship_coverage_audited
- verdict: _inconclusive_
- status: `no_membership_data`
- total sampled: 0, covered: 0, coverage: **0.00%**

## Interpretation guide

- **A1 FAIL** means delisted tickers lack last-close prices in cache. Until fixed, the broker-ledger replay must either skip these positions or use a conservative fallback (last-known close, with a written log).
- **A2 FAIL** below 95% means the historical universe is partially shrunk to survivors-only. CAGR/MDD numbers may be inflated by survivorship.
- **inconclusive** means data sources are missing (no membership file or empty price cache). Run the data collector first.
