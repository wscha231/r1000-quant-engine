# Run287 delisted coverage truth result (2026-07-15)

## Outcome

The current Alpha Vantage listing artifact does not contain historical
delisted coverage. It contains `14,140` active rows and zero usable delisted
rows. The previous `990/993` listing figure was the current universe's active
reference match, not evidence that delisted securities or survivorship bias
were covered.

The collector and coverage audit now distinguish these facts explicitly:

- active listing rows and current-universe active matches;
- delisted listing rows and current-universe delisted matches;
- non-CSV provider responses such as `{}`;
- whether any delisted source is available;
- whether the frozen five-row delisted sample minimum is met; and
- whether PIT universe membership is proven.

No active-only result can be described as delisted or survivorship coverage.

## Provider evidence

Alpha Vantage's official documentation exposes `state=delisted` and a
historical `date` parameter. However, two current observations returned the
same empty JSON object rather than CSV rows:

1. successful repository collection run `29064427303` used the configured key
   and persisted a two-byte `{}` delisted response; and
2. the official documented demo request for `2014-07-10` returned `{}` during
   this audit.

The provider response is still retained and hashed, but it is classified
`empty_json_object`, has `usable_listing_rows=false`, and cannot pass the
delisted sample gate. No paid endpoint, signup, email, or repeat request with a
private key was made.

Official reference:

- <https://www.alphavantage.co/documentation/#listing-status>

## Real artifact re-audit

The 993-name universe was re-audited with the actual successful-run listing
artifact, current Companyfacts/CIK reference, and downloaded forward estimate
snapshots.

| Evidence | Result | Interpretation |
| --- | ---: | --- |
| Alpha Vantage source rows | active 14,140 / delisted 0 | delisted source unavailable |
| Current-universe active reference | 990 / 993 | current identity/reference only |
| Current-universe delisted reference | 0 / 993 | no delisted evidence |
| SEC Companyfacts | 990 / 993 | actual filing coverage, already source-screened |
| Forward estimate attempted/seen | 855 / 993 | forward archive only |
| Forward estimate with real estimate | 17 / 993 | 1.71%, forward only |

The prior coverage snapshot had 839 attempted names and 13 names with a real
estimate. The increase to 17 is four names, about `+0.40%p`, below the frozen
`+5%p` threshold that could justify revisiting an otherwise identical failed
combination. Attempt visibility increased by 16 names, about `+1.61%p`, and
does not create historical estimate revision data.

SEC Companyfacts coverage previously rose from 739 to 990 names, but the
accepted-time filing-quality source screen already used the repaired broad
dataset and still failed OOS. That mapping repair is therefore already spent
evidence and cannot reopen the same SEC arm.

## CAGR/MDD relevance

This correction does not change a portfolio metric. It prevents a
survivorship-biased historical source from entering a source screen under a
misleading 99.7% coverage label. That protects both CAGR and MDD from a false
improvement that excludes failed or delisted securities.

The historical single A/B gate remains closed:

- external exact-time PIT estimate/guidance source: not ready;
- requested delisted sample minimum: not met;
- historical PIT universe membership: not proven;
- new coverage increase sufficient to repeat a failed arm: not met;
- eligible historical arm: zero.

The cost-efficient path is unchanged: continue bounded forward collection,
review the first 1D result only as a diagnostic, wait for the 21D direction and
63D mechanism gate, and accept a historical A/B only after a genuine 50-row
PIT/delisted/ADR source sample passes.

## Verification

- CSV versus `{}` response classification: passed;
- raw empty response retention and unusable-row labeling: passed;
- active/delisted loader separation: passed;
- active-only source cannot claim delisted coverage: passed;
- coverage report exposes zero delisted rows and known gap: passed;
- data coverage, catalog, and selection overlay smokes: passed;
- full local PR validation: `176/176` passed in `219.97` seconds;
- backtest, fullrun, target-book, order, weight, cash, production, and live
  trading actions: none.

## Evidence files

- `tools/collect_alphavantage_listing_status.py`
- `tools/audit_free_historical_data_coverage.py`
- `tests/free_historical_data_backfill_smoke.py`
- `_tmp_tests/run287_delisted_coverage_truth_20260715/summary.json`
- `outputs/free_historical_data_backfill_29064427303/`
