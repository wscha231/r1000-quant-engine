# Broker Gap Attribution

Diagnostic comparison of monthly/proxy accounting versus broker-ledger account replay.

Important: target-book forward returns are used only for attribution. They are not production signals.

| Portfolio | Legacy/Proxy CAGR | Broker CAGR | CAGR Gap | Legacy/Proxy MaxDD | Broker Daily MaxDD | Broker Month-End MaxDD | Avg Target Turnover | Trades | Fees | Diagnosis |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| main | 31.64% | 18.39% | 13.24pp | -15.69% | -33.75% | -31.43% | 51.29% | 3313 | $53,805 | high monthly target turnover creates execution cost and churn drag; monthly/proxy drawdown understates intramonth account drawdown; fees are material under realistic turnover |
| concentrated | 45.85% | 27.07% | 18.78pp | -17.11% | -39.18% | -29.35% | 57.77% | 499 | $84,828 | high monthly target turnover creates execution cost and churn drag; monthly/proxy drawdown understates intramonth account drawdown; fees are material under realistic turnover |

## Readout

- If broker daily MaxDD is much worse than legacy/proxy MaxDD, monthly accounting was hiding intramonth losses.
- If target turnover and fees are high, the strategy must be redesigned around account-aware holding, staging, and replacement rules.
- A proxy target pass is not promotion evidence until the broker-ledger path also passes.
