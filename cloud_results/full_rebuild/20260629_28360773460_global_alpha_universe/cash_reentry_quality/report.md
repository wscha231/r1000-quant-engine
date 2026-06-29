# Cash/Reentry Quality Audit

Measurement-only diagnostic. No cash-policy, target-book, or order mutation.

## Summary

- status: `completed`
- metric mode: `broker_ledger_next_close`
- production mutation allowed: `False`
- rows: 170
- cash trap rows: 170
- missing crisis-state rows: 0
- cash contract drift rows: 0

## Portfolio Cash

- `concentrated`: GREEN 18.2%, WATCH 46.4%, DEFENSE 70.4%, CRISIS 92.5%, latest 7.9%, cash_drag_vs_baseline -10.8%, cash_trap=True
- `main`: GREEN 15.1%, WATCH 20.7%, DEFENSE 43.5%, CRISIS 75.6%, latest 18.8%, cash_drag_vs_baseline -12.6%, cash_trap=True

## Cash Trap Rules

- GREEN avg cash > 10%.
- latest cash > 50% outside CRISIS.
- avg cash up but MDD improvement < 3pp.
- reentry cash normalization > 20 trading days.
