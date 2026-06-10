# Orchestrator Replay

- Status: `completed`
- Data mode: `historical_concentrated_monthly`
- Production activation allowed: `false`

## Metrics

| Portfolio | CAGR | Target | MaxDD | Target | Pass |
| --- | ---: | ---: | ---: | ---: | ---: |
| main_proxy | 33.76% | 25.00% | -13.33% | -20.00% | true |
| concentrated | 42.86% | 40.00% | -12.72% | -22.00% | true |
| unified_balanced | 26.53% | 28.00% | -10.14% | -22.00% | false |

## Interpretation

Replay used historical concentrated monthly returns and can be used as a challenger input.
Production remains blocked until target gates and human approval pass.
