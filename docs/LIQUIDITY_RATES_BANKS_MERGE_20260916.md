# Rates + banks liquidity slice — 2026-09-16

Status: `RESEARCH_ONLY`. This is the first causal merge slice from the liquidity/crisis research. It does **not** merge historical-crisis prediction, adaptive-model promotion, sector/theme ranking, or portfolio target changes.

## What is merged

- matched `SOFR` / `IORB` funding evidence with the actual pair date;
- `WLCFLPCL` primary-credit level/change as emergency funding evidence;
- weekly `TOTCI` business loans and `DPSACBW027SBOG` deposits;
- quarterly `DRTSCILM` lending standards and `DRSDCILM` loan demand;
- explicit `NON_SESSION`, `NOT_RELEASED`, `MISSING`, `WITHDRAWN` handling;
- structural-break protection for simple bank-loan growth;
- read-only attachment to the existing canonical state.

## Interpretation

A fresh SOFR point does not count as a new funding-stability confirmation unless a same-economic-date IORB observation is available. IORB can contain weekend dates, so a newer IORB calendar date by itself is not a gap: the pair is anchored to the latest SOFR economic date.

Bank-credit `EXPANSION_EVIDENCE` requires all of the following at once: positive 13-week C&I loan growth, nonnegative 13-week deposit growth, stronger loan demand, and non-tightening standards. A loan-stock jump alone is not called organic expansion. Structural breaks invalidate the simple growth calculation.

`STRESS`, `STABLE`, `EXPANSION_EVIDENCE`, `CONTRACTION_EVIDENCE`, and `MIXED` are research diagnostics. They are not trade instructions or portfolio weights.

## Source metadata rechecked on 2026-09-16

- SOFR: daily market rate, New York Fed / FRED.
- IORB: daily 7-day administered rate; replaced IOER/IORR from 2021-07-29.
- WLCFLPCL: weekly Wednesday primary-credit balance, USD millions.
- TOTCI: weekly ending Wednesday C&I loans, USD billions.
- DPSACBW027SBOG: weekly ending Wednesday deposits, USD billions.
- DRTSCILM / DRSDCILM: quarterly SLOOS supply/demand percentages.

References:
https://fred.stlouisfed.org/series/SOFR
https://fred.stlouisfed.org/series/IORB
https://fred.stlouisfed.org/series/WLCFLPCL
https://fred.stlouisfed.org/series/TOTCI
https://fred.stlouisfed.org/series/DPSACBW027SBOG
https://fred.stlouisfed.org/series/DRTSCILM
https://fred.stlouisfed.org/series/DRSDCILM

## Safety boundary

No scheduler, fullrun, accepted Drive ledger, target book, champion, order path, cash percentage, bond duration target, or live trading state is changed. Missing or invalid data degrades the context instead of becoming a favorable signal.

Historical PIT validation still requires archived vintages and era-specific policy-rate definitions. The current slice is safe for forward shadow diagnostics and later integration into the broader crisis/recovery system.

## Validation

The focused module has dedicated normal and optimized-interpreter tests. The merge gate must use the exact PR head; a green workflow proves software contracts only, not economic efficacy or current-market readiness.
