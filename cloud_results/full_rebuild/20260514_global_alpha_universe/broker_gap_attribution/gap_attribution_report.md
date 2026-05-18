# Broker Gap Attribution

Diagnostic comparison of monthly/proxy accounting versus broker-ledger account replay.

Important: target-book forward returns are used only for attribution. They are not production signals.

| Portfolio | Legacy/Proxy CAGR | Broker CAGR | CAGR Gap | Legacy/Proxy MaxDD | Broker Daily MaxDD | Broker Month-End MaxDD | Avg Target Turnover | Trades | Fees | Diagnosis |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| main | 35.52% | 18.44% | 17.08pp | -14.62% | -31.93% | -28.01% | 55.14% | 2873 | $34,566 | high monthly target turnover creates execution cost and churn drag; monthly/proxy drawdown understates intramonth account drawdown; cash/rounding/unfilled exposure drag is material; fees are material under realistic turnover |
| concentrated | 57.30% | 35.10% | 22.20pp | -13.66% | -22.68% | -19.59% | 61.19% | 649 | $69,041 | high monthly target turnover creates execution cost and churn drag; cash/rounding/unfilled exposure drag is material; fees are material under realistic turnover |

## Readout

- If broker daily MaxDD is much worse than legacy/proxy MaxDD, monthly accounting was hiding intramonth losses.
- If target turnover and fees are high, the strategy must be redesigned around account-aware holding, staging, and replacement rules.
- A proxy target pass is not promotion evidence until the broker-ledger path also passes.
