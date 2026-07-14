# Run287 exact packet input registry - 2026-07-14

## Outcome

The same-close input-registry builder is implemented. It consumes one explicit
source bundle with exactly twelve paths, validates every manifest date and
status, verifies the required internal output hashes, verifies all selector
price-map sources, freezes the input file hashes, and publishes one immutable
registry per valuation date.

The builder never discovers a latest directory and never calls the network.
Missing bundles safely skip. Missing, extra, stale, unsafe, hash-mismatched, or
same-date changed inputs block. A byte-identical same-date rerun reuses the
existing registry; an older registry cannot replace a newer current pointer.

## Actual 2026-07-13 validation

- registry status: `READY_EXACT_PACKET_INPUTS_REVIEW_ONLY`;
- valuation close: `2026-07-13`;
- dynamic manifests: `6`;
- fixed inputs: `6`;
- selector price-map sources checked: `363`;
- price-source mismatches: `0`;
- contract failures: `0`;
- registry build time: about `0.33` seconds;
- registry SHA-256:
  `f592436927f961ea717467c1db90bab4d4909d18281db9b94ab3758d1fb655c4`;
- network, order, target-book, backtest, fullrun, production, and live-trading
  operations: `0` or `false`.

The new registry was then used from a fresh packet root. The producer returned
`READY_EXACT_SELECTOR_RISK_PACKET_REVIEW_ONLY` in about `11.47` seconds with
three selector scenarios and the same seven candidates: `AMAT`, `ARM`, `COHU`,
`DELL`, `FTNT`, `PANW`, and `STX`. The old and new selector comparisons matched
exactly across 50 rows and 15 semantic columns. Candidate-risk output matched
exactly across seven rows and 53 semantic columns after excluding only
environment-specific file and event identifiers.

## Daily workflow behavior

The completed-close workflow now attempts this sequence after marking the
paper accounts and building the holding-risk watch:

1. read `outputs/run287_exact_packet_input_sources/source_bundle.json`;
2. build or reuse the immutable same-date registry;
3. run the exact selector/risk packet producer only through that registry;
4. ingest the packet only when `exact_packet_ready=true`;
5. otherwise skip or block without selecting a fallback portfolio.

The workflow does not yet create the source bundle. The remaining upstream
engineering gate is a bounded orchestrator for exact-close price, macro,
decision-frame, score-stack, crisis, and benchmark manifests. This change
provides its explicit handoff and removes the hand-written registry step.

## Volatility finding and performance boundary

The 2026-07-13 close demonstrates why broad market and security-level risk must
remain separate. The frozen market crisis state was `GREEN` with crisis score
about `0.0784`, while the exact-close marked accounts estimated:

| Portfolio | 1D return | Cash | ALERT weight | WATCH weight |
|---|---:|---:|---:|---:|
| Main | -5.4295% | 11.2533% | 26.0836% | 39.7181% |
| Concentrated | -6.0107% | 17.4686% | 27.7027% | 29.6086% |

SNDK alone contributed about `-3.7634%p`, or roughly 62.6% of the Concentrated
one-day loss. The detector therefore found the idiosyncratic damage, but one
event cannot validate a sell, trim, replacement, or cash rule. Such a rule
would also overlap rejected stop, partial-resize, cluster-cap, and generic
technical-risk mechanisms.

Performance strengthening is consequently split into two honest clocks:

- current risk resilience starts immediately through immutable exact-close
  observations and resolved 1/5/21/63/126-session outcomes;
- historical CAGR/MDD modification starts only after a genuinely timestamped
  PIT estimate/guidance source passes its single-source full/OOS/OOS2 gate.

No current weights changed. Historical metrics remain Main
`34.4032% / -25.3619%` and Concentrated `49.0971% / -22.9552%`.

## Tests

Targeted tests cover ready publication, exact reuse, immutable-date collision,
stale bundle, unsafe upstream mutation, internal output corruption, price-map
source hashes, missing-bundle skip, workflow ordering, and the real-data
end-to-end semantic comparison.

Full local PR validation passed `169/169` in `236.11` seconds.

## Evidence

- `docs/run287_exact_packet_input_source_bundle_contract.json`
- `tools/build_run287_exact_packet_input_registry.py`
- `tests/run287_exact_packet_input_registry_smoke.py`
- `.github/workflows/daily_operating_selection_refresh.yml`
- `outputs/run287_exact_packet_input_registry_20260714_local/`
- `_tmp_tests/run287_exact_packet_from_registry_20260714/`
