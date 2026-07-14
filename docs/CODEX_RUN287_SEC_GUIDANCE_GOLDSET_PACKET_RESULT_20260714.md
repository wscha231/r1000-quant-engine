# Run287 SEC guidance gold-set packet result — 2026-07-14

## Outcome

The bounded SEC management-guidance scout is now frozen as a dual-review
packet. The packet contains every one of the 80 preregistered filings, not just
the 16 heuristic candidates, so both precision and false-negative recall can
be measured before parser or return work starts.

- status: `READY_FOR_DUAL_REVIEW`;
- issuers: `10`, including all `5/5` ADR/global sample names;
- filings: `80/80`;
- exact index acceptance: `80/80`;
- raw SEC acceptance-header agreement: `80/80`;
- valid per-filing SHA-256: `80/80`;
- heuristic-candidate filings: `16`;
- heuristic-negative filings retained for recall review: `64`;
- separate blank reviewer packets: `reviewer_a`, `reviewer_b`;
- returns, portfolio state, and outcome labels in the packet: `0`.

No return join, portfolio A/B, target-book mutation, fullrun, production, live
trading, or automatic order ran.

## Frozen evidence

The hardened v3 offline replay reused the existing SEC submission cache. It
added the cache path and complete-submission SHA-256 to every successful
download row, then verified the raw `<ACCEPTANCE-DATETIME>` header before the
source hash was admitted.

The gold-set builder fails closed unless all of these remain true:

- the source scout reports `READY_FOR_MANUAL_SCHEMA_REVIEW`;
- exact accepted-time and raw-header agreement are both `100%`;
- no bounded row is missing or quarantined;
- all 80 source hashes match the cached bytes;
- the filed-date fallback is disabled;
- all execution and portfolio flags remain false.

The frozen input hashes are:

| Input | SHA-256 |
|---|---|
| Gold-set contract | `3e017f5a71cf3fd349909c4369db5f7555bf4d52643b80ac4c157a2790d5c3fb` |
| Scout contract | `1a0ee18a84b266d66b73f8d9947cf8303b27921362420ff7ec6d3e562c1bcd07` |
| Scout summary | `dd034078cc7c5baf572d0d9a91ddfb50e0fabee5d5fc03120465f823edde0c98` |
| Download log | `74d06162b803702a6ca70a290bc69876bf292f4f4cc0aaea7c1b38f52226bc47` |
| Heuristic candidates | `4bd971e818adcdfeb5c139356ebe0c5444de41095db2b5ea0351e46728175864` |
| Review manifest | `8273d2116c27269ab57365557bc9b27ef36e5d2629944c6e52a87aa050717a7d` |

## Review contract

Both reviewers receive the same full allowed-document text and heuristic
passages, but separate blank label files. They must independently classify all
80 filings without seeing one another's labels. Any disagreement requires
adjudication. Missing labels are not negative labels.

The initial registered extraction scope is intentionally narrow:

- filing class and heuristic precision label;
- EPS and revenue only;
- fiscal period and period type;
- low, high, midpoint, currency, unit, GAAP basis, and share basis;
- exact accepted text span;
- prior-guidance accession and `INIT/UP/DOWN/NO_CHANGE/NOT_COMPARABLE`.

Expansion to the 45-name active archive stays blocked unless the completed
gold set reaches at least 90% precision, 80% recall, and 80% registered-schema
completeness. Fired rows must have 100% accepted-time, fiscal-period, currency,
unit, and share-basis completeness.

## Verification

The new synthetic smoke passed and covers:

- inclusion of heuristic candidates and negatives;
- distinct blank reviewer outputs;
- full source-hash and accepted-time verification;
- unsafe-operation flags remaining false;
- fail-closed behavior on a source-hash mismatch.

The adjacent SEC scout smoke also passed. The repository-wide smoke reported
six pre-existing sparse-checkout failures because `aggressive/` and the tracked
IWB seed are absent from this checkout; no new SEC test failed.

## Next gate

Complete the two independent reviews, adjudicate disagreements, and calculate
precision, recall, and schema completeness. Only if those frozen gates pass may
a deterministic parser be implemented and tested against this gold set. No
return labels are joined at this stage.

## Evidence files

- `docs/run287_sec_guidance_goldset_contract.json`
- `tools/build_sec_guidance_goldset_packet.py`
- `tests/sec_guidance_goldset_packet_smoke.py`
- `outputs/run287_sec_management_guidance_scout_20260714_hardened_v3/`
- `outputs/run287_sec_guidance_goldset_packet_20260714/`
