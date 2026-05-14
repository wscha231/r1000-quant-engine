# Broker Gap Attribution

Diagnostic comparison of monthly/proxy accounting versus broker-ledger account replay.

Important: target-book forward returns are used only for attribution. They are not production signals.

| Portfolio | Legacy/Proxy CAGR | Broker CAGR | CAGR Gap | Legacy/Proxy MaxDD | Broker Daily MaxDD | Broker Month-End MaxDD | Avg Target Turnover | Trades | Fees | Diagnosis |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| main | 35.93% | 20.20% | 15.73pp | -16.29% | -32.02% | -27.89% | 54.91% | 2791 | $34,259 | high monthly target turnover creates execution cost and churn drag; monthly/proxy drawdown understates intramonth account drawdown; cash/rounding/unfilled exposure drag is material; fees are material under realistic turnover |
| concentrated | 54.90% | 29.42% | 25.49pp | -13.38% | -32.56% | -29.48% | 59.69% | 280 | $58,620 | high monthly target turnover creates execution cost and churn drag; monthly/proxy drawdown understates intramonth account drawdown; cash/rounding/unfilled exposure drag is material; fees are material under realistic turnover |

## Readout

- If broker daily MaxDD is much worse than legacy/proxy MaxDD, monthly accounting was hiding intramonth losses.
- If target turnover and fees are high, the strategy must be redesigned around account-aware holding, staging, and replacement rules.
- A proxy target pass is not promotion evidence until the broker-ledger path also passes.
