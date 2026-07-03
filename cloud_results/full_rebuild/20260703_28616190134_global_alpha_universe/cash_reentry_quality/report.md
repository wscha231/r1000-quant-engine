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

- `concentrated`: GREEN 21.9%, WATCH 50.3%, DEFENSE 69.9%, CRISIS 95.3%, latest 16.8%, cash_drag_vs_baseline 0.6%, cash_trap=True
- `main`: GREEN 15.9%, WATCH 19.0%, DEFENSE 44.2%, CRISIS 80.4%, latest 5.0%, cash_drag_vs_baseline -9.3%, cash_trap=True

## Cash Trap Rules

- GREEN avg cash > 10%.
- latest cash > 50% outside CRISIS.
- avg cash up but MDD improvement < 3pp.
- reentry cash normalization > 20 trading days.
