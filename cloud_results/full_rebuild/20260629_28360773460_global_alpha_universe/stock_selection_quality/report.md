# Stock Selection Quality Audit

Measurement-only diagnostic. No strategy, target-book, sizing, cash-policy, universe, or gate mutation.

## Summary

- status: `completed`
- metric mode: `broker_ledger_next_close`
- production mutation allowed: `False`
- candidate rows: 46772
- selected rows: 1675
- available ex-ante leader rows: 4300
- missed ex-ante leader rows: 3818
- forward label benchmark: `SPY`
- forward labels used for ranking: `False`

## Rejection Reasons

- `candidate_gate`: 1654
- `cap_or_replacement`: 656
- `cash`: 1493
- `unknown_requires_investigation`: 15

## Interpretation Rules

- Missed leaders are defined from T-date ex-ante features only.
- Forward returns are labels for review, not live selection signals.
- Top7/Form4/ETF evidence cannot be a standalone buy reason.
- Missing evidence is not a penalty.
- Negative FCF is not a hard reject for Emerging lane.
