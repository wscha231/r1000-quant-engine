# Orchestrator Replay

- Status: `completed`
- Data mode: `historical_concentrated_monthly`
- Production activation allowed: `false`

## Metrics

| Portfolio | CAGR | Target | MaxDD | Target | Pass |
| --- | ---: | ---: | ---: | ---: | ---: |
| main_proxy | 32.78% | 25.00% | -11.41% | -20.00% | true |
| concentrated | 42.74% | 40.00% | -14.45% | -22.00% | true |
| unified_balanced | 26.15% | 28.00% | -8.99% | -22.00% | false |

## Interpretation

Replay used historical concentrated monthly returns and can be used as a challenger input.
Production remains blocked until target gates and human approval pass.
