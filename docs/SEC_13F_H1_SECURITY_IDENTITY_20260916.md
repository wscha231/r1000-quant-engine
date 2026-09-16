# SEC 13F H1 Security Identity Preservation — 2026-09-16

Status: `RESEARCH_ONLY` / H1 data-integrity change only.

## Problem

The current institutional-signal path deduplicates holdings by `manager_cik + ticker + report_period` and computes position deltas by `manager_cik + ticker`. That can collapse a cash share row with CALL/PUT, another share class, or another CUSIP under the same ticker. A later option row can therefore overwrite cash-stock evidence or create false stock-level buys/sells.

## Change

- Define exact security identity using CUSIP, title of class, put/call, share type, investment discretion and normalized other-manager context.
- Fail closed when required identity or shares/value is missing or malformed.
- Apply amendment semantics before requiring one row per exact security identity.
- Preserve CALL/PUT/PRN rows in the validated holdings/event table.
- Restrict stock-level 13F selector evidence to cash `SH` rows only; options and PRN cannot drive the stock signal.
- Key quarter-to-quarter deltas and inferred exits by exact security identity, not ticker.
- On class/CUSIP rollover within one manager/ticker, simultaneous security increase/decrease is treated as mixed rather than a pure buy or sell.
- Preserve the late-restatement PIT rule: an inferred exit cannot be knowable before both the newer complete filing and any later prior-period restatement needed to establish the old security.
- Compute stock-conviction weights over cash-equity value rather than allowing option notional/value to dilute or inflate the denominator.

## Validation

New security-identity suite: 23 unique tests PASS in normal mode and Python `-O` mode. It covers cash/CALL/PUT preservation, cash-only stock aggregation, option isolation, CUSIP/class changes, exact-identity duplicate rejection, exit identity, NEW HOLDINGS semantics, late restatements, required-field/numeric fail-closed behavior, PIT cutoff, two-manager counting, deterministic row order, and CLI scope/error publication behavior.

Existing parser smoke was also run through all pre-contract legacy assertions after fixture identities were made explicit; the only remaining local blocker in the full smoke is the already-known parent H1 parser-integration suite's 3 real Parquet cases because this chat container lacks `pyarrow`/`fastparquet`. No test was weakened or skipped to hide that dependency gap.

## Non-claims / follow-ups

- The existing smart-money formula is not retuned here.
- `market_value_delta_usd` can still contain price-movement effects; flow/price decomposition is a separate measurement change.
- This change does not establish transaction dates from 13F, certify value units, resolve 13F-NT/reporting-scope relationships, or validate manager skill.
- This change does not add/remove a manager, alter the unified universe, select a stock, change portfolio weights, or trigger orders.
