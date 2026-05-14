# Live Trading Safety Audit

- Status: `blocked`
- Error count: 2
- Warning count: 0

This audit is pre-trade only. It does not place broker orders.

| Severity | Check | Message | Path |
| --- | --- | --- | --- |
| error | `concentrated_orders_nonpositive_qty` | orders contain non-positive quantities | `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/account_ledger_preview/concentrated/orders_preview.csv` |
| error | `concentrated_orders_blocked` | orders_preview contains blocked orders | `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/account_ledger_preview/concentrated/orders_preview.csv` |
