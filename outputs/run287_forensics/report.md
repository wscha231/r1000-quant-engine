# Run 28725350727 Forensic Attribution

This package is research-only. It does not dispatch another fullrun, tune thresholds, or promote production.

## Governance

- `production_promotion_allowed`: `False`
- `pit_universe_label_clean`: `False`
- `public_display_allowed`: `False`
- `live_trading_enabled`: `False`
- `decision_label`: `alpha_candidate_rejected_on_generated_book`
- `runner_parity_status`: `parity_documented_gap`
- `survivorship_inflation_estimate_cagr_pp`: `0.0`
- `survivorship_inflation_label`: `proxy`
- `survivorship_unmeasured_component`: `delisted_exclusion`

## Cash-Carry Replay Status

- `status`: `ready_for_exact_replay`
- `reason`: ready

## Window Attribution

| Portfolio | 2026-06-29 CAGR | 2026-07-02 CAGR | Delta pp | 2026-07-02 MaxDD | End equity delta |
| --- | ---: | ---: | ---: | ---: | ---: |
| main | 34.70% | 32.94% | -1.76 | -25.65% | -71,167 |
| concentrated | 49.23% | 46.99% | -2.24 | -23.22% | -167,416 |

The 2026-06-29 clamp is attribution-only. It is not a current pass label.

## Target-Book Drift

| Portfolio | Common dates | Avg ticker overlap | Avg L1 diff | Max L1 diff | Proxy delta sum |
| --- | ---: | ---: | ---: | ---: | ---: |
| main | 84 | 86.00% | 0.1177 | 0.5270 | -0.0428 |
| concentrated | 84 | 82.36% | 0.1311 | 0.8544 | -0.1068 |

## Metric Sidecar

| Arm | Portfolio | Metric mode | CAGR | MaxDD | Sharpe | Target pass |
| --- | --- | --- | ---: | ---: | ---: | --- |
| official_run287_zero_yield | main | broker_ledger_next_close | 32.94% | -25.65% | 1.237 | False |
| official_run287_zero_yield | concentrated | broker_ledger_next_close | 46.99% | -23.22% | 1.455 | False |
| generated_book_zero_yield | main | broker_ledger_next_close | 32.94% | -25.65% | 1.237 | False |
| generated_book_zero_yield | concentrated | broker_ledger_next_close | 47.00% | -23.22% | 1.455 | False |
| generated_book_cash_carry | main | broker_ledger_next_close_cash_carry | 33.81% | -25.36% | 1.262 | False |
| generated_book_cash_carry | concentrated | broker_ledger_next_close_cash_carry | 48.41% | -22.96% | 1.488 | False |

## Anti-Leakage Notes

- Frozen-book results are fixed-book research evidence, not regenerated fullrun acceptance.
- Regenerated-book results must be compared on the same metric mode and replay end date.
- Exact cash-carry replay is blocked until the price cache is present; it is not approximated here.
- Date/month/ticker attribution is diagnostic only. It must not be used to hand-edit losing months.
- Forward-label screens are audit labels only. Any rule sourced from them needs OOS validation before promotion.
