# Orchestrator Replay

- Status: `completed`
- Data mode: `historical_concentrated_monthly`
- Production activation allowed: `false`

## Metrics

| Portfolio | CAGR | Target | MaxDD | Target | Pass |
| --- | ---: | ---: | ---: | ---: | ---: |
| main_proxy | 34.30% | 25.00% | -16.02% | -20.00% | true |
| concentrated | 41.28% | 40.00% | -16.26% | -22.00% | true |
| unified_balanced | 26.74% | 28.00% | -12.14% | -22.00% | false |

## Interpretation

Replay used historical concentrated monthly returns and can be used as a challenger input.
Production remains blocked until target gates and human approval pass.
