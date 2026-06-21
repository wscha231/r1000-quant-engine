# Stock Selection Quality Audit

Measurement-only diagnostic. No strategy, target-book, sizing, cash-policy, universe, or gate mutation.

## Summary

- status: `completed`
- metric mode: `broker_ledger_next_close`
- production mutation allowed: `False`
- candidate rows: 45990
- selected rows: 1607
- available ex-ante leader rows: 4175
- missed ex-ante leader rows: 3708

## Rejection Reasons

- `candidate_gate`: 1612
- `cap_or_replacement`: 627
- `cash`: 1469

## Interpretation Rules

- Missed leaders are defined from T-date ex-ante features only.
- Forward returns are labels for review, not live selection signals.
- Top7/Form4/ETF evidence cannot be a standalone buy reason.
- Missing evidence is not a penalty.
- Negative FCF is not a hard reject for Emerging lane.
