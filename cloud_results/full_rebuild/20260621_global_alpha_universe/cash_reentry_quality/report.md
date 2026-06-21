# Cash/Reentry Quality Audit

Measurement-only diagnostic. No cash-policy, target-book, or order mutation.

## Summary

- status: `completed`
- metric mode: `broker_ledger_next_close`
- production mutation allowed: `False`
- rows: 168
- cash trap rows: 168
- missing crisis-state rows: 0
- cash contract drift rows: 0

## Portfolio Cash

- `concentrated`: GREEN 21.3%, WATCH 50.7%, DEFENSE 70.8%, CRISIS 95.7%, latest 7.9%, cash_drag_vs_baseline -9.2%, cash_trap=True
- `main`: GREEN 15.3%, WATCH 21.0%, DEFENSE 43.2%, CRISIS 81.1%, latest 19.2%, cash_drag_vs_baseline -11.7%, cash_trap=True

## Cash Trap Rules

- GREEN avg cash > 10%.
- latest cash > 50% outside CRISIS.
- avg cash up but MDD improvement < 3pp.
- reentry cash normalization > 20 trading days.
