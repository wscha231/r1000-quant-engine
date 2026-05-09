# Orchestrator Replay

- Status: `completed`
- Data mode: `historical_concentrated_monthly`
- Production activation allowed: `false`

## Metrics

| Portfolio | CAGR | Target | MaxDD | Target | Pass |
| --- | ---: | ---: | ---: | ---: | ---: |
| main_proxy | 35.07% | 25.00% | -14.03% | -20.00% | true |
| concentrated | 43.85% | 40.00% | -19.94% | -22.00% | true |
| unified_balanced | 27.30% | 28.00% | -11.79% | -22.00% | false |

## Interpretation

Replay used historical concentrated monthly returns and can be used as a challenger input.
Production remains blocked until target gates and human approval pass.
