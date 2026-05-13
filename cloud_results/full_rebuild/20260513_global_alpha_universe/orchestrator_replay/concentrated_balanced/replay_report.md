# Orchestrator Replay

- Status: `completed`
- Data mode: `historical_concentrated_monthly`
- Production activation allowed: `false`

## Metrics

| Portfolio | CAGR | Target | MaxDD | Target | Pass |
| --- | ---: | ---: | ---: | ---: | ---: |
| main_proxy | 32.28% | 25.00% | -13.98% | -20.00% | true |
| concentrated | 46.26% | 40.00% | -15.08% | -22.00% | true |
| unified_balanced | 26.65% | 28.00% | -10.57% | -22.00% | false |

## Interpretation

Replay used historical concentrated monthly returns and can be used as a challenger input.
Production remains blocked until target gates and human approval pass.
