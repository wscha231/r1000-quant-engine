# Run287 SEC Filing Quality Source Screen Closure

## Decision

The preregistered `sec_filing_quality_event` source screen is rejected. No Main
negative veto, Concentrated confirmed replacement, fixed-book replay, generated-
book replay, or combined package is allowed from this signal.

This is a closure and reproducibility change. The exact lost source-screen code
and smoke were restored from commit `2f3c9750`; the failed source screen was not
rerun or retuned.

## Data-contract integrity

- Eligible exact accepted-time filings: `115,185`.
- Unique issuer/accession source-screen events: `113,466`.
- Positive / negative / neutral ticker events: `6,362 / 7,193 / 101,630`.
- Fired rows with exact acceptance: `100%`.
- Filed-date fallback used: `false`.
- Current identity mapping is not historical membership:
  `pit_universe_label_clean=false`.
- Event parquet SHA-256:
  `7aa0c7283228e3ab244434967f671535ad175f5a3884d4ff7f904d43a95d68b4`.
- Source-screen rows SHA-256:
  `0dfc1c101753d91df28b80f695018a0a480e71fbd703cc73896c6e1e10d2fcd5`.
- Restored producer SHA-256:
  `b42a2371ed545c7fee68038f50f2ab5588776c7bad17db374bd5d587ddd50ca4`,
  exactly matching the frozen source-screen manifest.

The source screen collapses current multi-share-class mappings to unique
`cik10 + accession_number`, enters at the first adjusted market close strictly
after exact `accepted_at`, and clusters bootstrap resamples by filing week.

## Frozen results

Primary 63-session positive-minus-negative returns were:

| Segment | Positive | Negative | Difference | Filing weeks | 95% lower |
|---|---:|---:|---:|---:|---:|
| Full | 12.5621% | 3.5899% | +8.9722%p | 347 | -0.0792%p |
| OOS | 4.3755% | 4.2012% | +0.1743%p | 89 | -1.2681%p |
| OOS2 | 4.2471% | 3.7522% | +0.4950%p | 163 | -0.6535%p |

Every segment was well above the minimum 100 positive events, 100 negative
events, and 12 independent filing weeks. The failure is therefore not an
underpowered exit:

- OOS and OOS2 63D bootstrap lower bounds are negative.
- Full 63D lower bound is also slightly negative.
- OOS 21D positive-minus-negative is negative at `-0.2468%p`.
- OOS2 21D is positive but its lower bound is `-0.4763%p`.
- OOS/OOS2 126D point estimates are only `+0.0833%p / +0.3515%p`, with
  negative lower bounds `-2.7228%p / -1.6776%p`.

The mandatory rule required positive full/OOS/OOS2 direction and nonnegative
OOS/OOS2 63D filing-week bootstrap lower bounds. The frozen verdict
`REJECT_SOURCE_SCREEN` is correct.

## Reproducibility and stop rule

- `tools/run_sec_filing_quality_event.py` and
  `tests/sec_filing_quality_event_smoke.py` were restored byte-for-byte from
  commit `2f3c9750`.
- The offline smoke passes and remains part of standard PR validation.
- The exact signal/mechanism/book/window is registered in
  `docs/run287_do_not_repeat_registry.json`.
- Threshold, horizon, component weight, percentile, ticker, or era retuning is
  prohibited after seeing these outcomes.
- A future lane must use genuinely different signal semantics or application
  mechanism, or a preregistered material coverage increase. Renaming this event
  does not qualify.

No target book, cash weight, order, CAGR/MDD label, fullrun, production, or live
trading state changed.
