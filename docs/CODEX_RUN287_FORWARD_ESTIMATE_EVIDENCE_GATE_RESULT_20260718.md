# Run287 forward estimate evidence gate result (2026-07-18)

## Outcome

The durable Google Drive archive is healthy enough to continue as a forward
paper lane, but it is not historical PIT evidence and is still underpowered.
The exact status is `UNDERPOWERED_FORWARD_PAPER`.

No historical backtest, generated-book experiment, target-book change, order,
cash-policy change, fullrun, production action, or live-trading action was
performed.

## Real archive evidence

The audit read the existing Drive state through 2026-07-18 without making a
provider request.

| check | observed | gate/result |
|---|---:|---|
| Daily snapshot files | 8 | all 8 latest date hashes match the append-only index |
| Snapshot rows | 1,329 | no duplicate ticker/date row |
| Attempted/seen tickers | 1,016 | current/proxy identities across daily rotations, not a PIT universe |
| True forward-estimate tickers | 35 / 993 (3.52%) | archive coverage only |
| Increase from frozen 13-name baseline | +22 names, +2.2155pp | below the +5pp same-arm repeat threshold |
| Exact timezone-bearing `available_from` | 0 / 1,329 | historical source screen blocked |
| Future-availability violations | 0 | pass |
| Stable vendor event ID | absent | historical source screen blocked |
| Delisted metadata | absent | historical source screen blocked |
| ADR/global identity metadata | absent | historical source screen blocked |

The latest 2026-07-18 collection attempted 55 names and returned six true FMP
estimate rows. Finnhub remained blocked by its run-scoped entitlement circuit;
the latest index records 92 avoided estimate requests. On 2026-07-17 the same
lane returned zero true estimate rows. Missing rows remain neutral.

The 1,254 Finnhub rows with `has_forward_estimate=0` still contain numeric zero
placeholders in estimate fields. The new gate explicitly refuses to count
non-null numeric fields as coverage; only `has_forward_estimate>0` qualifies.

## Real paper-ledger evidence

The durable ledger through the 2026-07-17 close contains:

- six decision dates;
- 348 observations and 82 unique tickers;
- 22 distinct tickers actually observed in the true-forward arm, versus the
  required 50;
- zero resolved 21D, 63D, or 126D outcomes;
- zero completed 21D or 63D decision-week blocks; and
- 62.86% archive-to-ledger true-ticker utilization (`22/35`).

Therefore the next action is only to continue the already bounded incremental
collection until the ledger reaches 50 distinct true-forward tickers. After
that, the system must wait for 200 unique 63D outcomes, 12 completed 21D week
blocks, and eight completed 63D week blocks without threshold retuning.

## Automation added

`tools/audit_run287_forward_estimate_evidence_gate.py` now joins the immutable
daily snapshot hashes, collection checkpoint, current-universe identity label,
and paper-ledger readiness into one fail-closed report. It distinguishes:

- `BLOCKED_FORWARD_EVIDENCE_CONTRACT` for malformed, future, duplicate, unsafe,
  or hash-mismatched present evidence;
- `UNDERPOWERED_FORWARD_PAPER` for valid but immature evidence; and
- `READY_FORWARD_PAPER_REVIEW_ONLY` only after every frozen sample threshold
  and the ledger's preregistered performance checks pass.

Even the ready state keeps historical acceptance false. The daily estimate
workflow now writes this gate after a completed market session, includes it in
the GitHub artifact/cache, and copies it to the durable Drive research state.
Focused collector, queue, manifest, workflow, and paper-ledger regressions
passed, followed by full local PR validation at `177/177` test files.

## CAGR/MDD impact

Historical generated-book evidence is unchanged because the new observations
start on 2026-07-09 and cannot be pasted into earlier rebalances:

- Main: CAGR `34.4032%`, MDD `-25.3619%`;
- Concentrated: CAGR `49.0971%`, MDD `-22.9552%`.

This work can improve future selection only if true estimate confirmation later
beats the matched ranks 31-60 control under the frozen 21D/63D/126D review
contract. It cannot close the current historical CAGR gaps by itself.

## Do not repeat

- Do not count zero-filled estimate columns when `has_forward_estimate=0`.
- Do not call 1,016 attempted current symbols historical universe coverage.
- Do not use date-only `available_from` as an accepted-time historical event.
- Do not reopen the same historical arm for a +2.2155pp coverage change.
- Do not tune on the first 21D result or treat paper readiness as historical
  CAGR/MDD acceptance.

## Evidence files

- `docs/run287_forward_estimate_evidence_gate_contract.json`
- `tools/audit_run287_forward_estimate_evidence_gate.py`
- `tests/run287_forward_estimate_evidence_gate_smoke.py`
- `.github/workflows/earnings_estimates_daily.yml`
- `outputs/run287_forward_estimate_evidence_gate_20260718/summary.json`
- `outputs/run287_forward_estimate_evidence_gate_20260718/snapshot_daily.csv`
- `outputs/run287_forward_estimate_evidence_gate_20260718/report.md`
