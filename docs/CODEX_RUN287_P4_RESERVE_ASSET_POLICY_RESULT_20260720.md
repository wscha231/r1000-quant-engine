# Run287 P4 ReserveAssetPolicy result - 2026-07-20

## Decision

One canonical `ReserveAssetPolicy` now covers historical broker replay,
same-close target metadata, order preview, paper bootstrap, and the durable
forward paper ledger. Reserve reasons reconcile separately, so structural
capacity cash is no longer labeled crisis cash.

The research default remains `DGS3MO_CARRY`; the forward paper default remains
`BROKER_CASH_OR_MMF`. No current paper account was migrated and no operating
stock target was changed. BIL is retained as a supported research mode but is
not adopted as the common default because Main MDD worsened. SGOV is explicitly
`BLOCKED_SHORT_HISTORY` for the 2019-start generated book.

## Frozen comparison contract

- Main book SHA-256:
  `356bac22ec55090b2d2da882c7505b1460973227639a5d0b7a4c59c25c0ccff9`
- Concentrated book SHA-256:
  `848c1bac00985ab0b132794ee3e1c2942c1561d2f728b0a89778bd6c4e63660e`
- DGS3MO SHA-256:
  `d5f8c9bf116a918500107361c971e4de78ddf7835070511745c47a343b693490`
- Window: generated books from 2019-05-31 through market data 2026-07-10.
- Execution: adjusted close, next close, integer shares, 25 bps per side,
  maximum fill lag 7 days.
- No fullrun and no threshold grid.

## Metrics by mode

| Portfolio | Mode | CAGR | MDD | Sharpe | Avg / latest Reserve | Trades | Fees | Verdict |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Main | Broker cash / zero yield | 33.5352% | -25.6527% | 1.2506 | 29.2902% / 10.6925% | 1,625 | $41,949.52 | Exact control |
| Main | DGS3MO carry | 34.4032% | -25.3629% | 1.2757 | 29.3075% / 10.6339% | 1,625 | $42,922.45 | Historical default |
| Main | BIL total return | 33.7965% | -25.8378% | 1.2606 | 29.2865% / 10.7563% | 1,711 | $50,477.37 | Reject common adoption |
| Main | SGOV total return | - | - | - | - | - | - | `BLOCKED_SHORT_HISTORY` |
| Concentrated | Broker cash / zero yield | 47.6898% | -23.2216% | 1.4677 | 40.9638% / 16.3501% | 729 | $60,347.53 | Exact control |
| Concentrated | DGS3MO carry | 49.0968% | -22.9560% | 1.5002 | 40.9786% / 16.3955% | 730 | $62,764.08 | Historical default |
| Concentrated | BIL total return | 47.8700% | -23.0549% | 1.4760 | 40.9489% / 16.3816% | 812 | $77,173.65 | Research-only, not common default |
| Concentrated | SGOV total return | - | - | - | - | - | - | `BLOCKED_SHORT_HISTORY` |

DGS3MO versus zero yield added `+0.8680pp` CAGR and improved MDD by
`+0.2897pp` for Main. It added `+1.4070pp` CAGR and improved MDD by
`+0.2657pp` for Concentrated. These are Reserve accounting effects, not stock
selection alpha.

BIL added only `+0.2613pp` Main CAGR while worsening Main MDD by `0.1851pp`.
Its 85 Reserve fills added $8,281.21 of Main Reserve fees and $16,592.04 of
Concentrated Reserve fees. The P4 rule therefore prevents adoption based only
on CAGR. The fixed-book BIL mechanism is not to be retuned.

## Stress windows

| Portfolio | Mode | 2020 MDD | 2022 MDD |
| --- | --- | ---: | ---: |
| Main | Broker cash | -22.4014% | -13.9996% |
| Main | DGS3MO | -22.3744% | -13.6739% |
| Main | BIL | -22.3851% | -14.0848% |
| Concentrated | Broker cash | -20.8617% | -10.6983% |
| Concentrated | DGS3MO | -20.8395% | -9.6118% |
| Concentrated | BIL | -20.8862% | -10.0929% |

## Integrity results

- Canonical broker-cash mode reproduced legacy zero-yield metrics to `1e-12`
  and exact trade CSV hashes for both portfolios.
- DGS3MO uses calendar-day ACT/365 accrual and the latest rate whose
  `available_from` is no later than each accrual day. Future-rate use count was
  zero for both portfolios.
- ETF Reserve uses adjusted-close total return, next-close execution, integer
  shares, ordinary costs, and the shared lifecycle route in forward paper.
- ETF distributions and DGS3MO cash interest cannot be credited together.
  Double-count checks passed.
- All completed dates passed six-reason Reserve reconciliation.
- SGOV history began 2020-06-01, after the required 2019-05-31 start, and was
  not shortened or spliced.
- `fullrun_executed=false`, `production_enabled=false`,
  `live_trading_enabled=false`.
- Repository smoke tests passed `129/129`; full Tier-1 PR validation passed
  `183/183` in `744.61s`.

## Next gate

P5 may use the common Reserve and P3 risk state while evaluating hold, exit,
and replacement behavior. It must keep the historical DGS3MO baseline and the
current broker-cash paper default fixed, and must not use BIL costs or carry to
mask a stock-selection result.
