# Stock Selection Quality Audit

Measurement-only diagnostic. No strategy, target-book, sizing, cash-policy, universe, or gate mutation.

## Summary

- status: `completed`
- metric mode: `broker_ledger_next_close`
- production mutation allowed: `False`
- candidate rows: 45990
- selected rows: 1612
- available ex-ante leader rows: 4200
- missed ex-ante leader rows: 3735

## Rejection Reasons

- `candidate_gate`: 1634
- `cap_or_replacement`: 625
- `cash`: 1463
- `unknown_requires_investigation`: 13

## Interpretation Rules

- Missed leaders are defined from T-date ex-ante features only.
- Forward returns are labels for review, not live selection signals.
- Top7/Form4/ETF evidence cannot be a standalone buy reason.
- Missing evidence is not a penalty.
- Negative FCF is not a hard reject for Emerging lane.
