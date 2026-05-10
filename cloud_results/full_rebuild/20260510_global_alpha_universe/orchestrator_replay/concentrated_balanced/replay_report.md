# Orchestrator Replay

- Status: `completed`
- Data mode: `historical_concentrated_monthly`
- Production activation allowed: `false`

## Metrics

| Portfolio | CAGR | Target | MaxDD | Target | Pass |
| --- | ---: | ---: | ---: | ---: | ---: |
| main_proxy | 32.48% | 25.00% | -13.06% | -20.00% | true |
| concentrated | 42.07% | 40.00% | -12.81% | -22.00% | true |
| unified_balanced | 25.61% | 28.00% | -10.02% | -22.00% | false |

## Interpretation

Replay used historical concentrated monthly returns and can be used as a challenger input.
Production remains blocked until target gates and human approval pass.
