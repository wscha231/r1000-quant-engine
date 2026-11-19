# A4 daily direction learning inputs

Use one private restored input root for SPY, QQQ and the three existing RTDSM
vintages. The packet builder references the restored originals in place. Its
first output is a review candidate for 21, 63 and 126 sessions. The existing
A4 reader consumes `learning_request.json` after independent policy review.

## Evidence to pair with the supplier replies

| Evidence | What the reviewer checks |
| --- | --- |
| Rights evidence | Provider reply, applicable account and dataset scope for private statistical fitting, backtesting and the proposed storage and recurring use |
| Price original and source receipt | Exact bytes and the producer's deterministic extraction, adjusted or total-return basis, instrument/feed identity and treatment of corrections |
| Publication or capture evidence | Each exact closing value and the time it was first usable. Include the evidence for any revisions and check the one-hour decision deadline on the actual exchange calendar |
| RTDSM generations | Exact employment, CPI and unemployment workbook receipts, archive objects and research-use evidence |

The price export uses the existing learner's target-keyed JSON and fields
`session`, `value`, `original_sha256`, `return_basis`, `available_at`, and
`collected_at` for `FORWARD_CAPTURE_ONLY` origins. Use
`TOTAL_RETURN` or `PROVIDER_ADJUSTED_CLOSE_PROXY` with the reviewed basis.
Use the actual capture time for forward captures. A dated archive may provide
earlier availability when its evidence establishes the exact value then
visible. An ordinary end-of-day CSV provides observation dates. The clocks in
the export need separate evidence when the CSV carries dates alone.

For each price original, register a `a4-daily-direction-price-clock-export-v1`
JSON object with the following fields:

| Field | Value |
| --- | --- |
| `schema` | `a4-daily-direction-price-clock-export-v1` |
| `original_sha256` | Hash of the exact provider price original |
| `price_rows_sha256` | Hash of `encoded()` applied to the target-keyed lists of all exported rows using that original, preserving each list's order |
| `time_source_sha256` | Hash of the original publication log or capture evidence for those rows. This may be the same original when it includes the authoritative clocks |

## Prepare and review the private request

Create `daily_direction_source_request.json` below the restored input root.
Use real hashes from the private files and supply the fields below.

| Field | Value |
| --- | --- |
| `schema` | `a4-daily-direction-source-request-v1` |
| `cutoff` | Actual packet information cutoff with timezone |
| `calendar_origin_session`, `through_session` | First and last completed NYSE session in the declared study window. Keep the origin fixed for forward updates |
| `policy_window` | `available_at` and `expires_at` for independent review. The runtime checks the policy again at execution |
| `trial_identity` | Existing do-not-repeat registry fields `signal`, `mechanism`, `book` and `window` |
| `prices` | `{path, sha256}` for the normalized price export, relative to the private root |
| `price_sources` | Keyed by price original SHA256. Each value contains `historical_use`, `price_series_id`, `rights_evidence_sha256`, `source_receipt_sha256` and `price_publication_clock_evidence_sha256` |
| `objects` | SHA256-keyed `{path, sha256}` refs for price originals, rights, source receipts and clock evidence, including every `time_source_sha256` used by a clock export |
| `vintage` | `root` relative to the private packet root and `generations` keyed by `rtdsm_employ`, `rtdsm_pcpi` and `rtdsm_ruc`. Each generation entry has `generation_sha256` and `rights_evidence_sha256`. Include those rights objects in `objects` |

```sh
python -m tools.prepare_a4_daily_direction_inputs --root <private-input-root> stage
```

The candidate directory under `a4_learning_candidates/<policy-sha256>/`
contains the exact `policy.json`, `inputs.json` and `review.json`. The coverage
report includes per-symbol missing and late closes, the common on-time count
and the last common on-time session. Preserve gaps on the NYSE grid. Inspect the
source receipts and clocks against the normalized rows,
then have the existing policy reviewer pin the exact policy bytes.

```sh
python -m tools.prepare_a4_daily_direction_inputs --root <private-input-root> \
  seal --reviewed-policy-sha256 <independently-reviewed-policy-sha256>
python -m tools.a4_daily_direction --input-root <private-input-root> \
  --policy-sha256 <independently-reviewed-policy-sha256> --output <private-result-json>
```

`seal` rechecks the evidence objects and existing A4 input validation before
writing the immutable `learning_request.json`. Repeating identical work reuses
the same bytes. Stage a new packet root for changed input or evidence. Use the
existing private restore and readback route for the hosted `A4_ONLY` cycle.
Supply a fresh reviewed packet as inputs change. The harness covers the
offline preparation path and leaves operational data approval to the
independent reviewer.
