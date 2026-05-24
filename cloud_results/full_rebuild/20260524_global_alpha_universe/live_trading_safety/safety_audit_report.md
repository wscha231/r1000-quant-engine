# Live Trading Safety Audit

- Status: `pass`
- Error count: 0
- Warning count: 1

This audit is pre-trade only. It does not place broker orders.

| Severity | Check | Message | Path |
| --- | --- | --- | --- |
| warning | `concentrated_large_order` | single order exceeds review threshold | `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/account_ledger_preview/concentrated/orders_preview.csv` |
