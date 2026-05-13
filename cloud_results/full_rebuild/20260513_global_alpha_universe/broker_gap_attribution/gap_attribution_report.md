# Broker Gap Attribution

Diagnostic comparison of monthly/proxy accounting versus broker-ledger account replay.

Important: target-book forward returns are used only for attribution. They are not production signals.

| Portfolio | Legacy/Proxy CAGR | Broker CAGR | CAGR Gap | Legacy/Proxy MaxDD | Broker Daily MaxDD | Broker Month-End MaxDD | Avg Target Turnover | Trades | Fees | Diagnosis |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| main | 32.85% | 21.38% | 11.47pp | -13.98% | -33.19% | -28.72% | 53.28% | 2091 | $37,667 | high monthly target turnover creates execution cost and churn drag; monthly/proxy drawdown understates intramonth account drawdown; cash/rounding/unfilled exposure drag is material; fees are material under realistic turnover |
| concentrated | 53.94% | 37.35% | 16.59pp | -14.88% | -37.89% | -21.58% | 63.89% | 525 | $81,872 | high monthly target turnover creates execution cost and churn drag; monthly/proxy drawdown understates intramonth account drawdown; fees are material under realistic turnover |

## Readout

- If broker daily MaxDD is much worse than legacy/proxy MaxDD, monthly accounting was hiding intramonth losses.
- If target turnover and fees are high, the strategy must be redesigned around account-aware holding, staging, and replacement rules.
- A proxy target pass is not promotion evidence until the broker-ledger path also passes.
