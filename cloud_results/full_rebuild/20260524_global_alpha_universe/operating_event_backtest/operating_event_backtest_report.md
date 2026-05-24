# Operating Event Backtest Verification

This report separates daily risk-management evidence from full historical non-monthly entry/replacement evidence.

| Portfolio | Status | Daily risk engine | Non-monthly risk actions | Full non-monthly entries | Target max decisions/month | Broker CAGR | Broker MaxDD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | `partial_daily_risk_overlay_validated` | true | 526 | false | 1 | 21.45% | -32.45% |
| concentrated | `partial_daily_risk_overlay_validated` | true | 43 | false | 1 | 36.61% | -42.58% |

Interpretation:
- `partial_daily_risk_overlay_validated` means daily/weekly risk exits or trims can be replayed through an account ledger, but entry/replacement targets are still sourced from monthly or latest operating target books.
- `full_nonmonthly_entry_replacement_validated` requires target books with more than one decision date in at least one calendar month.
- If non-monthly risk actions are zero, the engine path can still be valid, but the latest artifacts did not encounter an observable daily/weekly risk trigger.
