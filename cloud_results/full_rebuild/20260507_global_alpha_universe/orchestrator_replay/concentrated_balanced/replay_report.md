# Orchestrator Replay

- Status: `completed`
- Data mode: `historical_concentrated_monthly`
- Production activation allowed: `false`

## Metrics

| Portfolio | CAGR | Target | MaxDD | Target | Pass |
| --- | ---: | ---: | ---: | ---: | ---: |
| main_proxy | 33.55% | 25.00% | -13.90% | -20.00% | true |
| concentrated | 42.95% | 40.00% | -15.92% | -22.00% | true |
| unified_balanced | 26.87% | 28.00% | -11.09% | -22.00% | false |

## Interpretation

Replay used historical concentrated monthly returns and can be used as a challenger input.
Production remains blocked until target gates and human approval pass.
