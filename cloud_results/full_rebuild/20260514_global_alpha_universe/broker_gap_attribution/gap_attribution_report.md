# Broker Gap Attribution

Diagnostic comparison of monthly/proxy accounting versus broker-ledger account replay.

Important: target-book forward returns are used only for attribution. They are not production signals.

| Portfolio | Legacy/Proxy CAGR | Broker CAGR | CAGR Gap | Legacy/Proxy MaxDD | Broker Daily MaxDD | Broker Month-End MaxDD | Avg Target Turnover | Trades | Fees | Diagnosis |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| main | 34.53% | 23.10% | 11.44pp | -14.36% | -29.98% | -27.49% | 54.26% | 2727 | $39,076 | high monthly target turnover creates execution cost and churn drag; monthly/proxy drawdown understates intramonth account drawdown; cash/rounding/unfilled exposure drag is material; fees are material under realistic turnover |
| concentrated | 55.05% | 33.00% | 22.06pp | -17.94% | -41.82% | -32.37% | 64.39% | 402 | $69,818 | high monthly target turnover creates execution cost and churn drag; monthly/proxy drawdown understates intramonth account drawdown; fees are material under realistic turnover |

## Readout

- If broker daily MaxDD is much worse than legacy/proxy MaxDD, monthly accounting was hiding intramonth losses.
- If target turnover and fees are high, the strategy must be redesigned around account-aware holding, staging, and replacement rules.
- A proxy target pass is not promotion evidence until the broker-ledger path also passes.
