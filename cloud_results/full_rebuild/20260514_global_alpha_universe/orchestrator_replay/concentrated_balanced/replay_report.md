# Orchestrator Replay

- Status: `completed`
- Data mode: `historical_concentrated_monthly`
- Production activation allowed: `false`

## Metrics

| Portfolio | CAGR | Target | MaxDD | Target | Pass |
| --- | ---: | ---: | ---: | ---: | ---: |
| main_proxy | 35.12% | 25.00% | -16.29% | -20.00% | true |
| concentrated | 43.19% | 40.00% | -14.97% | -22.00% | true |
| unified_balanced | 27.55% | 28.00% | -12.70% | -22.00% | false |

## Interpretation

Replay used historical concentrated monthly returns and can be used as a challenger input.
Production remains blocked until target gates and human approval pass.
