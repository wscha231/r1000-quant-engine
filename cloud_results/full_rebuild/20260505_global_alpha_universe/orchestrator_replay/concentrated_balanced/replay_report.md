# Orchestrator Replay

- Status: `completed`
- Data mode: `historical_concentrated_monthly`
- Production activation allowed: `false`

## Metrics

| Portfolio | CAGR | Target | MaxDD | Target | Pass |
| --- | ---: | ---: | ---: | ---: | ---: |
| main_proxy | 34.42% | 25.00% | -16.61% | -20.00% | true |
| concentrated | 39.11% | 40.00% | -18.38% | -22.00% | false |
| unified_balanced | 26.60% | 28.00% | -12.90% | -22.00% | false |

## Interpretation

Replay used historical concentrated monthly returns and can be used as a challenger input.
Production remains blocked until target gates and human approval pass.
