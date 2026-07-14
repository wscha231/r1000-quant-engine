# Run287 forward durability and improvement plan

## Decision

Historical CAGR/MDD cannot be guaranteed forward.  The system must separate:

1. validated historical evidence;
2. daily implementation fidelity;
3. true-forward outcome evidence; and
4. new alpha research.

The daily simulated fill ledger belongs to layers 2 and 3.  It is not allowed
to replace the historical acceptance metrics.

## Current validated endpoint

As of the completed 2026-07-10 XNYS close, the temporal broker extension has:

| Portfolio | CAGR | MDD | Target gap |
|---|---:|---:|---:|
| Main | 34.4032% | -25.3619% | CAGR +0.5968%p; MDD +0.3619%p recovery needed |
| Concentrated | 49.0971% | -22.9552% | CAGR +0.9029%p needed; MDD gate already passes |

Contract: integer shares, next close, 25 bps per side, DGS3MO cash carry with
one-business-day availability lag.  The extension preserved the frozen price,
trade, and equity prefixes exactly.

## Evidence that must not be retuned

- Main growth downside-beta neutralization was a genuine near miss but is
  terminally rejected: CAGR 35.0843%, MDD -25.2237%.  It missed the MDD gate by
  0.2237%p, so the same signal/mechanism/window must not be threshold-tuned.
- SEC market-confirmed fundamental events had positive point estimates but
  negative OOS and OOS2 filing-week bootstrap lower bounds.  Its source screen
  verdict is `REJECT_SOURCE_SCREEN`; no portfolio arm is allowed.
- The cash-opportunity and MDD-contributor reports are diagnostics, not A/B
  evidence.  They may motivate a preregistration but cannot justify hindsight
  ticker exclusions, broad gross floors, or crisis threshold changes.

## Daily durability monitor

Every completed market close should produce a private append-only paper state:

- schedule at 10:15 KST Tuesday-Saturday, then use the exact NYSE calendar to
  skip weekends, holidays, and stale sessions while honoring early closes;
- require the completed session's exact close for every held, targeted, or
  pending-order ticker before marking either account; never carry a prior close
  into a new public as-of date;
- resolve only prior-day pending orders at the first eligible close;
- sell before buy, integer shares, 25 bps, no negative cash;
- hash-chain every fill and rejection;
- enqueue only when the normalized target allocation hash changed;
- retain quantities and dollars privately and publish only allowlisted fields;
- record daily equity, cash weight, pending count, rejection count, and target
  tracking state.

Forward status gates:

- any future-date fill, hash break, duplicate client order id, negative cash,
  cost mismatch, or same-day fill: `BLOCKED_INTEGRITY`;
- missing next close beyond seven calendar days: explicit rejection, never an
  invented fill;
- forward CAGR remains `UNDERPOWERED` before at least 252 observations and 300
  elapsed days;
- review checkpoints use 21/63/126-session return, with 252-session long
  confirmation and 504-session right-censored sensitivity added once resolved;
  also report SPY excess return, rolling drawdown, turnover, rejection rate,
  and implementation tracking error;
- forward evidence never changes the historical seven-year CAGR/MDD label.

## Cost-efficient improvement sequence

The remaining annualized gaps look small, but endpoint arithmetic is not an
acceptance test. Over roughly 7.1 years, moving Main from 34.4032% to 35% needs
about 3.2% more terminal wealth; moving Concentrated from 49.0971% to 50% needs
about 4.4% more. One narrow, repeatable winner-selection improvement may be
enough, but a lucky trade or endpoint-tuned threshold is not.

### 1. Preserve the current policy while the paper ledger accumulates

Do not modify selection, cash, or sizing from a few forward observations.  Use
the first 21 and 63 sessions to find execution drift, stale data, repeated
orders, and unintended cash accumulation.

### 2. Open one new source lane, not another proxy grid

The free SEC source lane is closed and the free estimate archive is still
forward-only.  The next historically testable lane should therefore be a
timestamped PIT earnings-estimate/guidance sample, subject to a procurement
gate before any full purchase:

- exact observation/availability timestamps;
- seven-year Russell-1000-like coverage including delisted history where
  licensed;
- EPS and revenue revision history plus guidance surprise;
- sample export sufficient to reproduce timestamps and corporate-action joins;
- fixed cost ceiling and no provider lock-in before a source screen passes.

The preregistered signal should be one composite revision state.  It must pass
single-source full/OOS/OOS2 screens before it can enter either portfolio.
The primary outcome remains 63 sessions, supported by 21 and 126 sessions.
Add a powered 252-session long-confirmation gate and a 504-session directional
sensitivity. Unresolved long outcomes stay null, and delisted securities need
verified delisting returns or cash proceeds rather than survivorship deletion.

This is the sole CAGR-gap research lane. Keep existing MDD controls frozen; do
not add a second exit, cash-floor, leadership-retention, or SEC threshold arm.
The first paid action is only a small timestamped sample with a fixed cost
ceiling. Full-universe licensing is allowed only if the sample proves PIT
timestamps, historical coverage, and nonnegative OOS/OOS2 source-screen
direction.

### 3. Portfolio use only after source validation

- Main: cancel only the incremental growth-transfer weight when the new PIT
  revision state is negative.  Baseline weights, cash, gross, cadence, and caps
  stay unchanged.  This targets the remaining 0.3619%p MDD gap without another
  direct growth or broad risk-proxy sweep.
- Concentrated: permit a selector-qualified challenger replacement only when
  the challenger revision state is positive and the incumbent is not positive;
  retain the existing 5% gross replacement ceiling.  Do not deploy cash through
  a broad gross floor.

### 4. Continue free forward evidence in parallel

Continue the bounded 993-name archive, ADR/foreign SEC queue, and matched
controls.  These data can reject weak ideas cheaply but cannot backfill
historical CAGR/MDD.

## Promotion boundary

No production or live-trading activation is allowed.  A candidate must still
pass source screen, fixed-book, generated-book, OOS/OOS2, cost sensitivity,
stress-era attribution, and concentration gates.  A fullrun requires separate
user approval after hashes and expected cost are reported.
