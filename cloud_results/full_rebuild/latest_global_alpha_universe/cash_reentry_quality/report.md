# Cash/Reentry Quality Audit

Measurement-only diagnostic. No cash-policy, target-book, or order mutation.

## Summary

- status: `completed`
- metric mode: `broker_ledger_next_close`
- production mutation allowed: `False`
- rows: 148
- cash trap rows: 148
- missing crisis-state rows: 0
- cash contract drift rows: 0

## Portfolio Cash

- `concentrated`: GREEN 22.9%, WATCH 50.3%, DEFENSE 73.1%, CRISIS 94.4%, latest 7.9%, cash_trap=True
- `main`: GREEN 16.4%, WATCH 19.1%, DEFENSE 46.3%, CRISIS 81.1%, latest 19.2%, cash_trap=True

## Cash Trap Rules

- GREEN avg cash > 10%.
- latest cash > 50% outside CRISIS.
- avg cash up but MDD improvement < 3pp.
- reentry cash normalization > 20 trading days.
