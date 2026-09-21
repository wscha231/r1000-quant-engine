# [PROJECT_HANDOFF] H1 research-price corporate-action basis — 2026-09-21

Issue: #474
Base: d4c5090fe3b1ad150488dfda184d4e065796b0a5\nPorted from stale PR #475 onto current master without cherry-picking the stale branch.
Scope: aggressive research price/RS input integrity only.

## Verified defect

aggressive/data_alpaca.py created StockBarsRequest without an explicit adjustment
and cached only by ticker/period. Alpaca historical stock bars default to raw
adjustment. A split can therefore enter momentum/relative-strength as a false
discontinuity, while an old raw cache can also survive a later semantic change
unless the basis is part of the cache key.

Current real counterexample: Amphenol (APH) completed 2-for-1 splits in 2024 and
2026. The fix is generic; there is no APH-specific code branch.

## Fix

- research RS/momentum defaults to adjustment=split;
- raw remains an explicit diagnostic option;
- only raw or split are admitted in this H1 scope; unknown values fail closed;
- cache identity changes to TICKER_PERIOD_ADJUSTMENT.parquet;
- ticker and benchmark fetches share one explicit adjustment basis;
- broker/execution exact-close price semantics are untouched.

This deliberately does not claim dividend-reinvested total return, repair
historical index membership, normalize ADR ratios, or change selection weights.

## Evidence boundary

The focused regression injects a fake Alpaca SDK and uses no network or secret.
It proves request adjustment propagation, raw availability, cache separation and
fail-closed unknown adjustment. Provider economic correctness and historical
price parity remain external evidence requirements.

## Separate next causal fix

TSM and other ADR share-basis normalization remains separate. TSMC official
financial statements state one ADR represents five ordinary shares; that identity
must be handled by a generic reviewed security-basis registry, not a
ticker-specific price hack.

No fullrun, backtest promotion, target, account/ledger, broker or order mutation
is authorized by this change.
