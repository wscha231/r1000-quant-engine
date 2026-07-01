# Cash-Carry Accounting Contract Draft - 2026-07-01

## Status

This is a draft governance contract. It does not change production metrics by itself.

Current status:

- Cash-carry is a research accounting improvement.
- `metric_mode=broker_ledger_next_close_cash_carry`
- `cash_carry_research_only=true`
- `production_activation_allowed=false`
- `pit_universe_label_clean=false` remains a standing production blocker.

## Motivation

Phase 1 measured cash-carry on the run `28436307420` official target books.

| Portfolio | Zero-yield baseline | Cash-carry | Delta |
|---|---:|---:|---:|
| Main | 34.27% / -24.11% | 35.11% / -23.99% | +0.84pp CAGR, +0.12pp MaxDD |
| Concentrated | 47.46% / -24.08% | 48.83% / -23.79% | +1.37pp CAGR, +0.28pp MaxDD |

Cash-carry improves both CAGR and MaxDD because the strategy holds real cash. In a real brokerage account, cash can be swept into money-market / T-bill-like instruments, but that must be specified before it becomes production evidence.

## Proposed Contract

If adopted, cash-carry accounting must use:

- rate source: `DGS3MO`
- PIT lag: `1 business day`
- haircut: `50bps`
- day count: `ACT/365`
- negative cash earns no interest
- cash interest is accrued only on positive cash balance
- all A/B arms in the same comparison use identical cash treatment
- zero-yield baseline is preserved for audit
- cash-carry baseline is preserved as a separate official research baseline

## Required Fields

Broker replay metrics must emit:

- `metric_mode`
- `cash_carry_mode`
- `cash_carry_research_only`
- `production_activation_allowed`
- `cash_rate_source`
- `cash_rate_lag_days`
- `cash_carry_haircut_bps`
- `cash_carry_day_count`
- `cash_interest_accrued_usd`
- `cash_interest_accrued_pct_starting_capital`
- `requested_replay_end_date`
- `actual_equity_curve_end_date`
- `end_date_matches_official`

Equity curve rows must expose enough detail to audit daily accrual:

- `cash_interest_daily`
- `cash_interest_accrued_to_date`
- `cash_rate_used`
- `cash_rate_available_from`

## Production Adoption Gate

Cash-carry can only become production evidence after a user-approved governance decision and after:

- `pit_universe_label_clean=true`, or an explicitly approved alternative evidence contract
- replay window is valid
- no future `available_from` leakage
- cash rate cache has PIT `available_from`
- production/paper broker cash treatment is defined
- benchmark comparison is made consistently, ideally with total-return handling documented

Until then:

```text
cash-carry = research accounting mode
```

not:

```text
production promotion evidence
```

## Open Governance Questions

1. Should AlphaOps officially include risk-free cash yield in production broker metrics?
2. Should zero-yield metrics remain the primary conservative baseline, with cash-carry as a secondary official view?
3. What real account cash vehicle should the production contract assume: brokerage sweep, T-bill ETF, money-market fund, or direct T-bill ladder?
4. Should cash yield be included in mission CAGR targets, or only in total-account reporting?

