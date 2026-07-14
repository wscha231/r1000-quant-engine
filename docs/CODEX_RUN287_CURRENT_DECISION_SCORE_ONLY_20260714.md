# Run287 current-decision score-only result - 2026-07-13 close

## Outcome

The four frozen linear model heads were evaluated for the verified 989-ticker
current-decision frame. The packet is ready for a separate score-stack parity
audit, but it does not authorize ranking, selection, sizing, a target-book
change, a backtest, fullrun, production, or live trading.

- Status: `READY_CURRENT_DECISION_SCORE_ONLY_NONRANKING`
- Valuation close: `2026-07-13`
- Decision time: `2026-07-14T05:00:00Z`
- Feature availability: `2026-07-13T23:59:59Z`
- Tickers: `989`
- Frozen model features: `238`
- Frozen heads: `4`
- Finite prediction cells: `3,956 / 3,956`
- Independent engine parity: `4 / 4`
- Maximum direct-matrix error: `< 1.0e-16`
- Network requests: `0`
- Source or target-book mutations: `0`

Canonical local evidence:

- `outputs/run287_current_decision_score_only_20260714_close_20260713/manifest.json`
- Decision-frame manifest SHA-256:
  `96e58406e9a82c9a3847f94dedfd9ff3c1a46127e7a77aa432c38823d40fda72`
- Score-only manifest SHA-256:
  `4cdbe8b64bfad53496fc4fbe759a98cb1ad0a519473001ae68f7e0fcdc63212e`
- Ticker-order predictions SHA-256:
  `d074996aebbde793b33c62c5db4ef69f0ad451554e9ed1780f3c6be70c0c44b1`
- Frozen model metadata SHA-256:
  `ebc0dee36c0838027b807e8673d798d190097e993fa9a73bd0acf0bf42d00e4c`

## Contract and validation

The new runner consumes one expected decision-frame manifest hash. It then
verifies the nested scaled matrix, selection context, ticker coverage, and
model metadata hashes before reading them. It fails closed when any of the
following is present:

- wrong decision-frame or nested input hash;
- a non-ready or non-research decision frame;
- a feature timestamp after decision time;
- a future feature row or missing-neutral violation;
- a nonfinite or out-of-order 989 x 238 matrix;
- a model metadata file with ranking enabled;
- coefficient shape or independent prediction parity failure.

The output preserves the input ticker order. It does not call the registered
cross-sectional score stack, sort a score, assign a rank, choose a top-N,
invoke a selector, calculate position weights, or write a book.

The smoke fixture also proves that a wrong manifest hash, future feature, and
ranking-enabled model all produce `BLOCKED_CURRENT_DECISION_SCORE_ONLY` before
predictions are emitted.

Local Tier-1 PR validation passed `160/160` in 238.8 seconds, including the
portfolio, cash, cost, PIT, current-decision, direct-fullrun guard, and public
dashboard contracts.

## Comparison with the prior embedded predictions

The decision frame retained prior prediction columns for diagnostic comparison.
They are not a parity baseline because that earlier context was incomplete and
used a different decision substrate.

- Prior finite coverage per head: `738 / 989`
- Current finite coverage per head: `989 / 989`
- Newly scored after complete scaled missing-neutral handling: `251`
- All 738 overlap rows changed beyond `1e-12` in every head.

Overlap Pearson correlations were `0.3115` for `pred_lin_ret`, `0.8025` for
`pred_lin_p`, `0.5485` for `pred_future_winner_ret`, and `0.6121` for
`pred_future_winner_p`. These shifts must not be interpreted as alpha or used
to select securities until the frozen score-stack contract is independently
reproduced.

DAL's refreshed accepted-time 10-Q is reflected in the new matrix. Its four
head deltas versus the embedded prior values are:

- `pred_lin_ret`: `-0.09147`
- `pred_lin_p`: `-0.04167`
- `pred_future_winner_ret`: `+0.07837`
- `pred_future_winner_p`: `-0.15187`

This is a model-input sensitivity observation, not a buy/sell decision.

## Safety and next gate

The packet explicitly records `decision_feature_complete=false` because raw
component coverage is not universal even though the frozen scaled model matrix
is complete under the registered missing-neutral contract. PIT universe
membership is also still unclean.

The next change must be a separate pinned score-stack parity audit consuming
the immutable ticker-order predictions and current selection context. It may
compare registered score construction but must still keep sorting, ranking,
selection, sizing, target-book writes, backtests, fullrun, production, and live
trading disabled. Only after that parity gate passes should an advisory
selector comparison and 25/50/100 bps turnover-cost review be opened.
