# Promotion Gate 20260516

## Non-Negotiable Gate

Promotion requires:

```text
metric_mode = broker_ledger_next_close
valid_for_production = true
next-close fills
integer shares
cash ledger
fees included
daily equity / daily drawdown
no forward-return leakage
human approval
```

## Portfolio Gates

| Portfolio | Baseline | First Target | Final Target | Promotion Rule |
| --- | --- | --- | --- | --- |
| Main | 21.84% / -28.62% | 25%+ CAGR / MaxDD no worse than -25% | 30%+ CAGR / -15% MaxDD | Must beat Main baseline officially |
| Concentrated | 35.10% / -22.68% | 40%+ CAGR / MaxDD no worse than -22% | 50% CAGR / -18% MaxDD | Must beat `20260514` officially |

## Required Checks

- A8 leakage audit passes.
- A8 PIT audit passes.
- A1 CIK/export schema audit passes.
- A6 broker-ledger replay passes.
- A6 cost sensitivity passes at 25/50/75/100 bps.
- A6 stress windows are reported.
- A7 hold-vs-replace and wrong substitution reports are attached.
- A0 baseline comparison table is updated.
- Human approval is recorded.

## Automatic Rejection

Reject promotion if any of the following is true:

- Candidate only beats legacy/proxy metrics.
- Candidate uses `backtest_metrics.json` as official proof.
- Candidate weakens its portfolio-specific baseline without a documented tradeoff and approval.
- Candidate writes challenger metrics into default official output directories.
- SEC evidence uses `transaction_date` instead of `accepted_at` / `available_from`.
- `latest 20260516` is presented as a promotion baseline.

## Output Labels

Research-only outputs must include:

```json
{
  "research_only": true,
  "production_activation_allowed": false
}
```

Official outputs must include:

```json
{
  "metric_mode": "broker_ledger_next_close",
  "valid_for_production": true
}
```
