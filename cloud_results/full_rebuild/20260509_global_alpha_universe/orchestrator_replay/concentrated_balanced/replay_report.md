# Orchestrator Replay

- Status: `completed`
- Data mode: `historical_concentrated_monthly`
- Production activation allowed: `false`

## Metrics

| Portfolio | CAGR | Target | MaxDD | Target | Pass |
| --- | ---: | ---: | ---: | ---: | ---: |
| main_proxy | 31.86% | 25.00% | -14.52% | -20.00% | true |
| concentrated | 45.90% | 40.00% | -13.46% | -22.00% | true |
| unified_balanced | 26.19% | 28.00% | -10.39% | -22.00% | false |

## Interpretation

Replay used historical concentrated monthly returns and can be used as a challenger input.
Production remains blocked until target gates and human approval pass.
