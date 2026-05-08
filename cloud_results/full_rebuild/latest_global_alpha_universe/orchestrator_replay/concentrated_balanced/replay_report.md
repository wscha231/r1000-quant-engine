# Orchestrator Replay

- Status: `completed`
- Data mode: `historical_concentrated_monthly`
- Production activation allowed: `false`

## Metrics

| Portfolio | CAGR | Target | MaxDD | Target | Pass |
| --- | ---: | ---: | ---: | ---: | ---: |
| main_proxy | 32.16% | 25.00% | -13.60% | -20.00% | true |
| concentrated | 42.93% | 40.00% | -14.86% | -22.00% | true |
| unified_balanced | 25.84% | 28.00% | -10.51% | -22.00% | false |

## Interpretation

Replay used historical concentrated monthly returns and can be used as a challenger input.
Production remains blocked until target gates and human approval pass.
