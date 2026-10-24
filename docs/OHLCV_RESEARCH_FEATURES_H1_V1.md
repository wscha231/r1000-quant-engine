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

The H1 consumer additionally requires `asset_class`, immutable
`provider_security_id` and `identity_evidence_sha256` on each instrument.
The evidence hash must belong to the generation's original `raw_source_sha256`
inventory and resolve through the existing bounded archive-object reader
(maximum 64 KiB). No Shared Reader, registry, generation schema or Source
producer is changed. This is a consumer-specific requirement on the existing
extensible instrument metadata; absent evidence keeps the output NULL/BLOCKED.

The object is an `ohlcv-security-identity-evidence-v1` source record containing
`provider`, `instrument_id`, `provider_security_id`, `ticker`, `asset_class`,
`market`, `mic`, `calendar`, `timezone`, `currency`, `valid_from`,
`valid_through`, `available_from`, `collected_at` and `expires_at`.
Its identity fields must match the instrument and source provider. The inclusive
effective interval covers the entire consumed price history; original aware
availability <= collection <= generation creation <= consumption <= expiry.
Unknown or conflicting records are refused, never inferred from ticker/class.
The supported regular-session MIC family is XNYS/XNAS/ARCX with NYSE/XNYS and
America/New_York; every consumed bar must be available after its completed
NYSE close, including ARCX where the unchanged research Reader does not make
that scheduled check. Unsupported MIC/calendar combinations stay blocked.
Subject type must be EQUITY or ETF. Raw/split reads bind the same identity
evidence and provider security ID as well as their existing price lineage.

Hash binding verifies source-record consistency, not the truth or authenticity
of an upstream assertion. Actual records still need A1 identity/rights/PIT
admission; all Source/economic authority remains false. Synthetic fixtures
explicitly use CONTRACT_FIXTURE and prove only the calculation/refusal contract.

SPY is the primary benchmark. A requested SPY ID must resolve to ticker SPY
and source-bound type ETF; Nasdaq Composite must resolve to source-bound INDEX.
SPY's MIC comes from its time-effective source evidence, not a hardcoded XNYS
assumption. The positive ARCX/XNAS examples are synthetic contract fixtures,
not recovered or admitted SPY/Composite data.
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

The Windows worktree's unchanged legacy pattern-memory contract has raw CRLF
bytes differing from its canonical Git-LF immutable pin. The whole legacy
caller stops before the H1 suite in that context; it is not a full Native PASS.
Run the registered H1 `run_contract_suite` directly to verify its 38 original
and 10 new unittest methods in both modes, and report this separately from
fresh hosted CI of the complete caller. No historical contract hash is rebound.

Existing 16-name preview ZIP SHA256:
`a9f670d213a51965b0cd9151ff4fe758e3f2fa59bbbbbdab1e0ba0cb44523252`.
Its preview/report are reused unchanged. They contain no admitted frozen
Shared Reader generation and no matching SPY source. They are not a native
calculation/authentication result of this new API. Actual16 remains
BLOCKED_ACTUAL_SOURCE_GENERATION; native positive tests are CONTRACT_FIXTURE only.
No raw recollection or new historical-identity/PIT claim is made.

## Integrated Main component consumer (2026-10-24)

The snapshot uses the public research-only `read_components()` once for the
adjusted subject and explicitly optional benchmarks, each with its own declared
history start. An optional RAW companion uses its exact separate generation.
Reader exceptions abort the snapshot; only returned optional component refusals
preserve subject features. Identity evidence checks remain consumer-specific.
One invocation reuses its verified component results, never a cross-snapshot
admission cache. Manifest planning reads do not certify the manifest; the Reader
revalidates the exact original bytes and complete global inventory. The component
reference records REQUESTED_COMPONENTS_ONLY and whole_generation_verified=false.
There is no subset generation, latest/cache fallback, Source/PIT promotion,
provider GET or change to training/backtest/selector/ER/portfolio authority.
The public Reader API is integrated in master `37809837` through PR627. This
Main implementation reuses the original `c0146e33` capability and the pinned
three-file `8b9dbd9a` preparation patch; it does not vendor Reader code. The
original 49 test method ASTs, 31 unrelated builder functions and independent
oracle Git bytes are preserved. Additional integration cases retain all seven
prepared cases and verify role aliases, absent optional inventory, explicit
windows, unchanged OBV anchoring, and global identity/resource refusal.

Requests deduplicate stable instrument IDs before one split-generation batch.
Subject/benchmark role checks remain separate after the verified result is
reused. The declared window spans the source's retained history through the
completed target session, preserving the consecutive-suffix OBV anchor. A
481-session optimization is not applied. Out-of-window partitions remain
explicitly unverified; no complete-generation claim follows from the batch.
An absent optional instrument reaches the public Reader and its named local
refusal; planning does not silently drop it. Global hash, clock, identity,
resource and Lake failures block the snapshot, including the optional RAW call.

Current-head Native, independent A6 and GitHub evidence must be recorded after
implementation. All positive inputs remain synthetic contract fixtures unless
a separately pinned qualified real generation is actually read. Actual16,
actual Source-to-Feature-to-existing-research-reference ACK and economic
admission remain NOT_RUN/BLOCKED when that generation is unavailable. No new
Registry or ingestion/collection dependency is introduced here.
