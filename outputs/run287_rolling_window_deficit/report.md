# Run287 Rolling Window Deficit

Status: `completed`

This is equity-curve-only attribution. It does not replay trades, mutate
target books, dispatch a fullrun, or tune thresholds.

## Summary

| Portfolio | Actual end | CAGR | MaxDD | Target pass | Delta CAGR vs 2026-06-29 | Last 20 CAGR pctile | Last 20 pass rate | Last 252 pass rate |
| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| main | 2026-07-02 | 33.81% | -25.36% | false | -1.77pp | 10.0% | 0.0% | 0.0% |
| concentrated | 2026-07-02 | 48.41% | -22.96% | false | -2.27pp | 25.0% | 35.0% | 2.8% |

## Interpretation

- Low latest-end percentile means the `2026-07-02` endpoint is a poor
  endpoint relative to nearby endpoints; do not fit a rule directly to it.
- A broad low pass rate means the deficit is structural across many
  endpoints and needs ex-ante alpha/risk work.
- A high pass rate with a low latest-end percentile points to end-date
  shock sensitivity rather than a general alpha failure.
- A low pass rate across many endpoints means the target is not robustly
  met even if the immediate endpoint shock explains the last few days.
