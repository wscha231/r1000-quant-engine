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

- `concentrated`: GREEN 21.9%, WATCH 50.3%, DEFENSE 71.8%, CRISIS 95.3%, latest 7.9%, cash_drag_vs_baseline -12.6%, cash_trap=True
- `main`: GREEN 16.5%, WATCH 19.0%, DEFENSE 44.8%, CRISIS 80.4%, latest 19.2%, cash_drag_vs_baseline -10.1%, cash_trap=True

## Cash Trap Rules

- GREEN avg cash > 10%.
- latest cash > 50% outside CRISIS.
- avg cash up but MDD improvement < 3pp.
- reentry cash normalization > 20 trading days.
