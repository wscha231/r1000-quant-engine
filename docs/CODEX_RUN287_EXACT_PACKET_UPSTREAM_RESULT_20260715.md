# Run287 exact packet upstream automation result (2026-07-15)

## Outcome

The daily completed-close workflow can now build the exact Run287 selector and
security-risk packet from its real upstream inputs. The prior workflow started
at the input registry, but never produced the required twelve-path source
bundle. That made daily risk observations skip even though the downstream
registry, selector, candidate-risk watch, archive, and outcome resolver were
already implemented.

The new bounded orchestrator runs only this review-only chain:

1. current 993-name scored-latest refresh;
2. macro sidecar and benchmark event;
3. accepted-time recent SEC delta and bounded Companyfacts delta;
4. current decision frame;
5. score-only and frozen score-stack eligibility audit;
6. frozen current-crisis reconstruction and SOXX benchmark recovery; and
7. an explicit, hash-validated twelve-input source bundle.

The existing registry and exact packet producer then consume that bundle. No
latest-directory discovery, portfolio fallback, selector retuning, backtest,
fullrun, target-book write, order generation, production activation, or live
trading is allowed by this path.

## Frozen static substrate

The selector's old manifests refer to 363 exact historical parquet files that
are not reproducible from today's cache bytes. A deterministic archive was
therefore built from the verified local evidence rather than replacing those
files with newer data.

- archive file: `run287_exact_static_archive_v1.zip`
- archive bytes: `38,646,212`
- uncompressed bytes: `62,870,741`
- verified payload files: `387`
- frozen selector price sources: `363`
- archive SHA-256:
  `66ca4b6a6a61cb7e9a3a47e2f6d26aa42f30a9b96a25d07699c6cdeb8faf1d84`
- Google Drive folder: `research_static`
- Google Drive file ID: `1M1rbpFvG4NNmg5IMAGq93xRc6kWm_ek0`

The restore utility checks the archive hash, member set, every member hash and
size, the 363-file count, unsafe paths, and destination collisions before it
writes anything. It never deletes or overwrites a different file. The workflow
downloads the archive only when the GitHub cache misses; later runs reuse the
38.65 MB cache.

## Real portability and preflight evidence

The archive was restored into an isolated tree and joined to the real
2026-07-13 dynamic manifests. The source bundle and input registry both
returned READY. The registry validated all 363 price files with zero mismatch.
This also verified that legacy Windows paths can resolve inside the dedicated
archive tree on a Linux runner without basename or latest-file guessing.

A separate no-network preflight connected the restored archive to the real
Google Drive models, scored-OOS file, price cache, macro cache, current SEC
identity index, and company ticker map. It returned:

- status: `READY_EXACT_PACKET_UPSTREAM_PREFLIGHT_REVIEW_ONLY`
- universe rows: `993`
- estimated price-provider batches: `25`
- missing inputs: `0`
- hash mismatches: `0`
- network calls: `0`

The workflow also restores the older Drive location
`data_raw/sec/company_tickers.json` into the collector's current expected path
when the newer path is absent. Both inspected snapshots mapped all 993 universe
tickers when combined with the canonical SEC identity index.

## Cost and retry controls

The plan fixes per-stage ceilings and a total recorded-call ceiling of `130`.
The current 993-row universe estimates `25` price batches; macro is capped at
24 calls, benchmark at 1, recent SEC at 64, and Companyfacts at 8. The
orchestrator uses one unique attempt directory, stage timeouts, allowlisted
tools, explicit input paths, and exact expected READY statuses.

If the same valuation date already has a valid immutable bundle, a workflow
retry revalidates its manifests and hashes and reuses it with zero provider
calls. A changed, stale, missing, unsafe, or hash-mismatched same-date bundle
blocks instead of being silently replaced.

## CAGR/MDD relevance and boundary

This change removes an evidence-production bottleneck; it does not claim or
manufacture an immediate return improvement. Daily security-level warnings can
now become immutable observations and resolve into preregistered 1D, 21D, and
63D outcomes. That is what is needed to decide later whether any risk veto or
replacement mechanism improves future drawdown without destroying CAGR.

Historical generated-book evidence remains unchanged:

- Main: CAGR `34.4032%`, MDD `-25.3619%`;
- Concentrated: CAGR `49.0971%`, MDD `-22.9552%`.

The first 1D result remains diagnostic-only. It cannot change weights, cash,
exits, thresholds, or open an A/B. The two historical SEC source lanes remain
closed, and a new historical portfolio A/B remains blocked until a genuinely
PIT source passes the frozen source screen. Forward risk evidence must mature
to the existing 21D direction and 63D mechanism-review gates.

## Verification

- source-bundle focused smoke: passed;
- upstream and portable-path focused smoke: passed;
- workflow YAML and ordering smoke: passed;
- deterministic archive rebuild: byte-identical SHA-256;
- isolated archive restore: `387/387` files and `363/363` price sources;
- real 2026-07-13 portable registry: READY with zero contract failure;
- no-network 993-name upstream preflight: READY;
- full local PR validation: `175/175` test files passed in `218.29` seconds.

No fullrun, backtest, portfolio mutation, provider purchase, production action,
or live-trading action was performed. The next eligible completed-close run is
left to the scheduled workflow after the settlement buffer, avoiding an early
or duplicate manual dispatch.

## Evidence files

- `docs/run287_exact_packet_upstream_plan.json`
- `data_static/run287_exact_packet/best_thresholds.json`
- `tools/build_run287_exact_packet_source_bundle.py`
- `tools/run_run287_exact_packet_upstream.py`
- `tools/build_run287_exact_static_archive.py`
- `tools/restore_run287_exact_static_archive.py`
- `tests/run287_exact_packet_source_bundle_smoke.py`
- `tests/run287_exact_packet_upstream_smoke.py`
- `.github/workflows/daily_operating_selection_refresh.yml`
- `_tmp_tests/run287_exact_static_archive_v1_status.json`
- `_tmp_tests/run287_exact_static_restore_v1_status.json`
- `_tmp_tests/run287_static_portable_e2e/`
- `_tmp_tests/run287_exact_upstream_preflight/attempts/portable-preflight-20260715-v3/`
