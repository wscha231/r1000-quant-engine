# Incumbent/Challenger RS2W Audit - 2026-06-29

## Scope

This is a research-only follow-up to the Concentrated whipsaw diagnostics.  It
tests whether a 2-week relative-strength comparison between a reduced
incumbent and the contemporaneous capital-receiving challenger can identify
cases where the system should keep the incumbent instead of rotating.

It does **not** add `rs_benchmark_2w` to the production score.  Forward returns
are audit labels only.

## Implementation

Added:

- `tools/run_incumbent_challenger_opportunity_audit.py`
- `tests/incumbent_challenger_opportunity_audit_smoke.py`

Validation:

```text
python -m py_compile tools/run_incumbent_challenger_opportunity_audit.py tests/incumbent_challenger_opportunity_audit_smoke.py
python tests/incumbent_challenger_opportunity_audit_smoke.py
python tools/run_pr_validation.py --only incumbent_challenger_opportunity_audit
```

All passed locally.

## Clean 7Y Artifact Result

Input artifact:

- `artifacts/28074476465/outputs`
- target book: `alphaops_vnext/official_concentrated_target_book.csv`
- price cache: `artifacts/28074476465/cache_prices`

Command:

```text
python tools/run_incumbent_challenger_opportunity_audit.py \
  --latest-run artifacts/28074476465/outputs \
  --price-cache artifacts/28074476465/cache_prices \
  --portfolio concentrated \
  --output-dir artifacts/28074476465/incumbent_challenger_opportunity_audit_20260629 \
  --min-reduction 0.02 \
  --short-rs-days 10 \
  --forward-days 126 \
  --oos-start 2024-06-03
```

Output:

- `artifacts/28074476465/incumbent_challenger_opportunity_audit_20260629/summary.json`
- `artifacts/28074476465/incumbent_challenger_opportunity_audit_20260629/events.csv`
- `artifacts/28074476465/incumbent_challenger_opportunity_audit_20260629/predicate_summary.csv`

## Result

| predicate | events | positive rate | mean 126d excess | OOS events | OOS positive | OOS mean excess |
|---|---:|---:|---:|---:|---:|---:|
| all reductions | 263 | 44.5% | -14.77% | 73 | 31.5% | -53.92% |
| incumbent 2w RS stronger | 46 | 47.8% | -0.35% | 8 | 12.5% | -73.54% |
| incumbent 2w RS + long RS intact | 39 | 53.8% | +10.89% | 7 | 14.3% | -51.96% |
| incumbent 2w RS + score not worse | 13 | 53.8% | +35.35% | 3 | 0.0% | -81.76% |
| incumbent 2w RS + actual results positive | 33 | 51.5% | +6.42% | 5 | 20.0% | -72.74% |
| challenger 2w RS stronger | 217 | 43.8% | -17.83% | 65 | 33.8% | -51.51% |

Verdict:

```text
screen_reject_or_telemetry_only
next_action = do_not_add_rs2w_to_score
```

## Interpretation

2-week RS has some in-sample appeal when combined with long-RS or score
filters, but it collapses in OOS.  The primary predicate has only 13 full-period
events, 3 OOS events, and 0 OOS wins.  This is not enough to justify adding
2-week RS to `alphaops_vnext_score` or to a replacement gate.

The useful takeaway is narrower:

- Keep 2-week RS as review telemetry for incumbent/challenger diagnostics.
- Do not use it as a live ranking component yet.
- If revisited, it must be tested as a default-OFF hook with broader OOS sample
  support and broker-ledger A/B.

## Salvage From Rejected/Weak Experiments

Several rejected paths still contain side benefits worth preserving:

| path | primary decision | salvage |
|---|---|---|
| Concentrated score sizing | cap-safe arms did not improve CAGR enough; uncapped is not policy-safe | keep as upper-bound sizing diagnostic; do not use uncapped weight as policy |
| Whipsaw sell-throttle | rejected as CAGR lever: CAGR -0.30pp | possible risk/turnover reducer: MDD improved about +2.05pp, Sharpe +0.013, fees fell about $4.9k |
| AI Capex momentum tilt | not an MDD repair | keep as Main CAGR candidate: Main CAGR improved about +0.98pp with small MDD worsening |
| Event/cash/stop MDD repairs | no mission-quality tradeoff | keep only negative-evidence ledger; stop adding small cash/stop variants |
| 2-week RS incumbent comparison | rejected for scoring | keep as telemetry only; OOS collapse blocks policy use |

## Recommendation

Do not add 2-week RS directly to score.  The next useful work should focus on
larger, already-supported mechanisms:

1. Main CAGR: AI Capex tilt remains the cleaner positive broker-ledger candidate.
2. Concentrated CAGR: continue looking for hold-duration or selection-quality
   mechanisms with broker-ledger proof, not short-RS alone.
3. Risk sidecar: whipsaw throttle can be parked as a future risk reducer if the
   governance target values MDD/fees more than pure CAGR.

All paths remain research-only.  No production promotion, no live trading, and
no fullrun should be dispatched from this audit alone.
