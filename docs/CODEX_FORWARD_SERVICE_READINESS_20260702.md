# Forward Service Readiness Plan - 2026-07-02

## Decision

Current holdings are not a promise that the portfolio will keep compounding at
the backtested CAGR. The CAGR/MDD targets belong to the process, not to the
current names. Any public website must show this as a review-only, simulated
broker-ledger snapshot until a live forward ledger exists.

## Why This Layer Exists

The project has strong historical research artifacts, but a service needs a
separate forward evidence layer:

- a freeze-date paper ledger that records what was shown before future returns
  happen;
- expectation bands instead of point CAGR promises;
- alpha-decay and regime alarms;
- immutable snapshot hashes for every public view;
- explicit data-license and regulatory review before publication.

This is not an alpha lever and does not justify a fullrun.

## Implemented Seed

`tools/run_forward_service_snapshot.py` converts the latest official broker
replay state into a research-only service seed:

- `current_public_snapshot.json`
- `public_holdings.csv`
- `forward_ledger_seed.csv`
- `service_readiness.json`
- `report.md`

The tool reads broker-ledger artifacts only. It does not regenerate target books,
change weights, dispatch workflows, alter production gates, or create trade
orders.

Every snapshot and holdings row must carry:

- `backtest_metrics_are_simulated=true`
- `forward_expectation_basis="is_cagr_band_not_headline"`
- `cagr_display_policy="historical_cagr_is_simulated_backtest_not_forward_expectation"`

This is a data-contract guard, not only a UI guard. If public display is ever
enabled, downstream code must still see that historical CAGR is simulated
backtest context and not a forward return promise.

## Display Rules

Until all blockers clear, a website can only use the snapshot in an internal or
review-only display.

Required blockers:

- `pit_universe_label_clean=false` keeps production promotion blocked;
- live forward tracking has zero elapsed record at snapshot creation;
- cash-carry accounting requires explicit governance approval before it becomes
  a formal baseline;
- data vendor license review is required before commercial publication;
- Korea investment-advisory and disclosure review is required before public use;
- expectation bands and kill-switch rules are not yet materialized.

## Next Work

1. Start the forward ledger now. Time is the asset: a six-month live record only
   exists if the first freeze happens six months earlier.
2. Add expectation cone generation from historical monthly returns and realized
   forward ledger updates.
3. Add alpha-decay and regime alarms.
4. Harden scheduled refresh/fullrun completion before public use.
5. Keep all public snapshots hash-stamped and immutable.

## Non-Negotiables

- No production promotion.
- No live trading.
- No public return guarantee.
- No use of current holdings as a claim that historical CAGR will continue.
- No fullrun from this service layer alone.
