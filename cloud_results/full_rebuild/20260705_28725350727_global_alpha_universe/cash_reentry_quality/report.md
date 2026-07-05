# Cash/Reentry Quality Audit

Measurement-only diagnostic. No cash-policy, target-book, or order mutation.

## Summary

- status: `completed`
- metric mode: `broker_ledger_next_close`
- production mutation allowed: `False`
- rows: 172
- cash trap rows: 172
- missing crisis-state rows: 0
- cash contract drift rows: 0

## Portfolio Cash

- `concentrated`: GREEN 20.0%, WATCH 47.3%, DEFENSE 68.5%, CRISIS 92.7%, latest 16.8%, cash_drag_vs_baseline -4.7%, cash_trap=True
- `main`: GREEN 18.7%, WATCH 23.8%, DEFENSE 44.7%, CRISIS 76.5%, latest 10.8%, cash_drag_vs_baseline -8.7%, cash_trap=True

## Cash Trap Rules

- GREEN avg cash > 10%.
- latest cash > 50% outside CRISIS.
- avg cash up but MDD improvement < 3pp.
- reentry cash normalization > 20 trading days.
