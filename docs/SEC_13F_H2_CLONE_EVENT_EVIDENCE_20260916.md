# SEC 13F H2 Clone Event Evidence — 2026-09-16

Status: `RESEARCH_ONLY`.

This slice measures what an investor could have observed **after** a 13F became public.
It includes only `new` and `add` events, maps reporting CIKs to explicit economic
manager IDs, enters no earlier than the first trading session after disclosure,
and records 63/126/252/504-session outcomes with 0/2/5-session delayed-entry
variants.

The initial cost assumption is 10 bps per side and is preregistered only as a
baseline; it is not claimed optimal. Price provenance must explicitly certify
adjusted/total-return handling, calendar identity, frozen/PIT source identity,
benchmark identity and cost-model identity. Missing provenance fails closed.

Important boundaries:

- future prices in the cache do not make an outcome available before the target
  session matures at the decision cutoff;
- missing 504-session history is `PENDING_PRICE_HISTORY`, never a zero return;
- a benchmark calendar mismatch is blocked, not silently shifted;
- `trim`, `exit` and `hold` do not become positive clone-entry events;
- the module does not build a continuous portfolio NAV;
- it does not rank managers or validate the video's 70% 24-month claim;
- it does not change `managers.csv`, candidate scores, portfolio targets,
  orders, broker/paper books, champion state or live trading.

A later causal slice must aggregate reviewed event evidence into continuous or
otherwise explicitly defined clone books and only then produce the scorecard
contract consumed by the H2 manager policy in PR #442.
