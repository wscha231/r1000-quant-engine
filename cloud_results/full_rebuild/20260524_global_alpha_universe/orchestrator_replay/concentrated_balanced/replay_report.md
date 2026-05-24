# Orchestrator Replay

- Status: `completed`
- Data mode: `historical_concentrated_monthly`
- Production activation allowed: `false`

## Metrics

| Portfolio | CAGR | Target | MaxDD | Target | Pass |
| --- | ---: | ---: | ---: | ---: | ---: |
| main_proxy | 32.50% | 25.00% | -15.84% | -20.00% | true |
| concentrated | 38.68% | 40.00% | -24.39% | -22.00% | false |
| unified_balanced | 25.86% | 28.00% | -13.05% | -22.00% | false |

## Interpretation

Replay used historical concentrated monthly returns and can be used as a challenger input.
Production remains blocked until target gates and human approval pass.
