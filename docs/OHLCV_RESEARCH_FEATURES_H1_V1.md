# OHLCV research features H1 V1

Task: R1000-A2-OHLCV-TECHNICAL-FEATURE-H1-20261016. Parents #611/#612/#448.
This adds a pure, nonranking consumer in the existing OHLCV builder. It does
not collect data, construct a strategy, change the existing 21/63/126/252-day
strategy contract, run a study/backtest, or grant Source/PIT/economic admission.

## Entry and reuse

`tools.build_run287_ohlcv_location_timing_challenger.research_feature_snapshot`
accepts an existing `ResearchDataReader`, an exact generation SHA256, a stable
`security_id`, completed `session`, aware `as_of`, optional explicit benchmark
IDs and optional RAW generation. It returns one serializable feature/coverage
receipt. Repeated calls can cover different securities and sessions; each
snapshot is bound to its own cutoff and requested security. It writes nothing.

```python
from tools.build_run287_ohlcv_location_timing_challenger import research_feature_snapshot

row = research_feature_snapshot(
    reader, exact_generation_sha256,
    security_id=verified_security_id, session=completed_session,
    as_of=aware_consumption_cutoff,
    benchmark_ids={"SPY": verified_spy_id,
                   "NASDAQ_COMPOSITE": verified_composite_id},
    raw_generation=exact_matching_raw_generation_sha256,
)
```

`fixed_window_features` supplies existing returns, prior-only RVOL/Z-score,
ATR, close position, volatility ratio and accumulation/distribution arithmetic.
`aggressive.signals_technical.sma`, `slope_pct` and `obv` supply the other
primitive calculations. Full windows are enforced before accepting these
helpers' values. Legacy signal tiers, Fibonacci/strategy classifications,
`r1000_features.compute_three_level_relative_strength` and the Feature Frame
Pilot's model/scaler are not called: they emit scores, mixed horizons or neutral
fallbacks that do not satisfy this nullable per-session contract. No second
return/ATR/volume engine or score/rank is introduced.

## Definitions

All numeric returns/relative changes are fractions, except the named MA slope
which is percentage points per session. P is split-adjusted close. A prior
window excludes the current completed session.

| Output | Definition / minimum consecutive observed sessions |
|---|---|
| `ret_{n}s`, n=5/20/60/120/240 | P(t)/P(t-n)-1; n+1 |
| `rs_log_spy_{n}s` | log P(t)-log P(t-n)-log SPY(t)+log SPY(t-n); n+1 matched sessions |
| `rs_log_spy_change_{n}s` | RS_n(t)-RS_n(t-n); 2n+1 matched sessions |
| `nasdaq_composite_price_relative_{n}s` | (P(t)/P(t-n))/(Index(t)/Index(t-n))-1; n+1 matched sessions |
| `sma_{n}s`, n=20/50/150/200 | Arithmetic mean of n closes; n |
| `sma_{n}s_slope_pct_per_session_5` | OLS slope of last 5 full n-session SMAs / their mean ×100; n+4 |
| `rvol_20s_prior_only` | Current adjusted shares / mean of previous 20 sessions; 21 |
| `volume_z_20s_prior_only` | (Current shares - prior-20 mean) / prior-20 population SD; 21 |
| `raw_close_x_raw_volume` | Current raw close × raw shares, USD proxy; not actual tape turnover |
| `atr_14s`, `atr_14s_pct` | Arithmetic 14-TR average, optionally /close; 15; not Wilder smoothing |
| `realized_volatility_20s_over_63s` | Population SD of last 20 simple returns / last 63; 64 |
| `prior_high_{n}s`, n=20/60/252 | Maximum HIGH of exactly n prior sessions; n+1 |
| `breakout_prior_high_{n}s` | Current CLOSE strictly greater than prior n-session HIGH; n+1 |
| `obv_anchored` | Cumulative sign(close change) × adjusted shares; first observed anchor = 0; 2 |
| `obv_change_20s` | OBV(t)-OBV(t-20); 21 |
| `close_location_in_bar` | (Close-low)/(high-low), [0,1]; zero range => NULL |
| `accumulation_day_proxy` | Positive 1-session return, prior-20 volume Z≥0, close position≥0.65 |
| `distribution_day_proxy` | Negative 1-session return, prior-20 volume Z≥0, close position≤0.35 |

Accumulation/distribution are descriptive proxies, not identified institutional
flows. Missing operands yield NULL, never False or a neutral score. OBV's
explicit anchor is the start of the consecutive observed suffix, not a claim
about the security's entire lifetime.

## Frozen-input and calendar boundaries

The unmodified Shared Reader verifies source objects, manifests, aware source
availability/collection/expiry, row values, identities and receipt hashes. No
latest/cache/provider fallback is available. Source metadata assertions remain
upstream assertions; this consumer never independently certifies their truth.

The requested session must be a completed NYSE session under the installed
exchange calendar, including holidays and early closes; as_of cannot be future.
Every feature uses only rows through that session. Availability remains the
original aware clock; a later collection or a present-day as_of is never a
historical public-availability certificate. `historical_pit_certified` remains
False even when source metadata says VERIFIED.

The stock's price basis must be SPLIT_ADJUSTED. Source instrument metadata must
include explicit `halted_sessions` (sorted unique ISO dates; an empty list is an
upstream no-halt assertion for its covered window). Unknown halt coverage or a
halt at the target session blocks the snapshot. Historical halts/missing
sessions interrupt windows; prices are never filled or inner-join compressed.
An insufficient history or prelisting request yields NULL/refusal. A zero
volume bar is not independently interpreted as a trading halt.

Volume features additionally need `volume_basis=SPLIT_ADJUSTED` and a paired
RAW generation with `volume_basis=RAW`. Both must bind identical source run,
source receipt, raw source hashes, ticker, availability/collection and source
classification. Raw shares must be integral. On the entire consecutive
calculation suffix, adjusted OHLC must equal raw OHLC times the close-derived
factor, and adjusted shares times that factor must equal raw shares (rtol 1e-7,
atol 0). No missing paired session is filled. An OHLC factor mismatch blocks the entire snapshot; an inverse-share mismatch
blocks RVOL/Z/OBV/accumulation/distribution. The independently valid raw current turnover proxy
may remain available. A metadata label alone cannot unlock volume features.

SPY is the primary benchmark. A requested SPY ID must resolve to ticker SPY.
Nasdaq Composite requires an explicit ID resolving to ^IXIC/IXIC/COMP/^COMP;
QQQ is never a substitute. Stock and benchmark must share the exact frozen
generation, adjustment basis, currency/calendar, verified source PIT status,
original available clocks and every required session. No endpoint-only or
inner-join horizon shortening. Missing/invalid benchmark blocks only that
benchmark's features; it cannot erase valid stock-only observations.

## Output and verification

Each row includes stable security ID, ticker, session, as_of, source generation,
raw source SHA list, source receipt, read/file/row-set hashes, source clocks,
benchmark refs, raw ref, adjustment basis, code SHA and actual module/helper
SHA256, coverage, per-feature status and per-feature blockers. `snapshot_sha256`
binds the full result. A feature-complete state means calculation completeness
only. Source admission, historical PIT, selection, ranking, ER, portfolio and
orders remain False unconditionally.

The existing Tier-1 entry `tests/run287_ohlcv_location_timing_challenger_smoke.py`
runs the added unittest suite. Its checks remain active under Python -O;
unchanged legacy bare assertions are disabled under -O and their optimized
execution alone is not additional assertion coverage. Direct new-suite runs,
the registered caller and the unchanged Shared Reader have separate logs.
Independent QA reuses the exact offline oracle from the existing kickoff ZIP,
plus scalar arithmetic for RS changes, MA slopes, OBV and prior-high windows.
No author test is represented as independent A6.

Existing 16-name preview ZIP SHA256:
`a9f670d213a51965b0cd9151ff4fe758e3f2fa59bbbbbdab1e0ba0cb44523252`.
Its preview/report are reused unchanged. They contain no admitted frozen
Shared Reader generation and no matching SPY source. They are not a native
calculation/authentication result of this new API. Actual16 remains
SOURCE_RESTORED_NOT_ADMITTED; native positive tests are CONTRACT_FIXTURE only.
No raw recollection or new historical-identity/PIT claim is made.
