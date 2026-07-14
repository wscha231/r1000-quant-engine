# Run287 exact selector/risk packet producer - 2026-07-14

## Outcome

The zero-network half of the daily Run287 packet path is implemented. Given
one hash-pinned, same-close input registry, the producer now runs the frozen
no-write selector, derives the proposed-entry union, evaluates that union with
the frozen candidate-risk contract, and passes the exact pair explicitly to
the append-only archive.

The producer does not refresh the decision frame or score stack. Those
upstream stages must publish a `READY_EXACT_PACKET_INPUTS_REVIEW_ONLY`
registry for the same completed close. Missing, stale, changed, or incomplete
registries cannot fall back to the separate daily operating selector.

## Actual 2026-07-13 replay

- producer status: `READY_EXACT_SELECTOR_RISK_PACKET_REVIEW_ONLY`;
- exact rerun status:
  `READY_EXISTING_EXACT_SELECTOR_RISK_PACKET_REVIEW_ONLY`;
- selector scenarios: `3`;
- proposed-entry candidates: `7` (`AMAT`, `ARM`, `COHU`, `DELL`, `FTNT`,
  `PANW`, `STX`);
- network requests: `0`;
- first producer elapsed time: about `17.9` seconds;
- orders, target-book writes, backtests, fullrun, production, and live trading:
  all disabled;
- archive result against the existing 2026-07-13 history: zero new decision,
  scenario, position, and candidate rows because the normalized packet was
  identical.

The archive remains one decision date and one ISO decision week. Historical
metrics remain Main `34.4032% / -25.3619%` and Concentrated
`49.0971% / -22.9552%`; this operational automation is not CAGR/MDD evidence.

## Fail-closed workflow behavior

The daily completed-close workflow now runs in this order:

1. mark the paper accounts at the exact completed close;
2. build the held-security risk watch;
3. attempt the exact selector/risk producer from the same-date registry;
4. pass producer paths explicitly to the decision archive only when
   `exact_packet_ready=true`;
5. otherwise use a disabled discovery root so a restored or similarly named
   packet cannot be accepted accidentally;
6. continue user-facing review reports without changing a portfolio.

The producer also materializes portable copies of verified manifest outputs.
This removes stored Windows drive-letter paths without weakening file hashes.
The candidate contract and archive contract retain their frozen LF-byte hashes
on Windows only when the committed Git blob and parsed JSON both match exactly.

## Tests

Targeted checks passed:

- ready producer run with selector/risk invocation;
- exact same-date reuse without rerunning either stage;
- missing-registry safe skip;
- stale-registry block;
- portable manifest and price-map source verification;
- workflow ordering and artifact contract;
- existing archive idempotency;
- completed-close workflow gate.

Full local PR validation passed `168/168` in `225.10` seconds.

## Remaining bottleneck

The expensive upstream half is still separate: exact-close scored-latest,
bounded macro/benchmark/SEC inputs, decision frame, score-only, score stack,
crisis state, benchmark price, and the input registry. The next change should
make that registry producer bounded and resumable, with an explicit free
request ceiling. Until it is present for a date, the daily archive correctly
skips that date.

## Evidence

- `docs/run287_exact_packet_producer_contract.json`
- `tools/run_run287_exact_packet_producer.py`
- `tests/run287_exact_packet_producer_smoke.py`
- `.github/workflows/daily_operating_selection_refresh.yml`
- `outputs/run287_exact_packet_producer_20260714_local/`
- `outputs/run287_current_selector_no_write_exact_close_20260713/`
- `outputs/run287_candidate_risk_watch_exact_close_20260713/`
