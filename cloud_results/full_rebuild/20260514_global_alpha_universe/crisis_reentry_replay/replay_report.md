# Crisis Ladder + Bargain Reentry Replay

Research-only replay. Production weights are unchanged.

- Status: `completed`
- Source cash: `reported_regime_by_month`
- Production CAGR / MaxDD: 30.62% / -16.88%

| Policy | CAGR | Sharpe | MaxDD | Avg Cash | Turnover | Production Allowed |
|---|---:|---:|---:|---:|---:|---:|
| `fast_reentry` | 32.08% | 1.877 | -13.65% | 8.64% | 54.11% | false |
| `bargain_reentry` | 30.88% | 1.880 | -12.97% | 11.61% | 52.74% | false |
| `crisis_ladder` | 30.64% | 1.880 | -12.43% | 12.65% | 51.68% | false |

## Limits

- Uses exported monthly holdings and macro policy rows, so it is directional until wired into the full production accounting path.
- It tests cash timing only; it does not discover new tickers.
- Policies that reduce cash can raise CAGR while worsening stress-window drawdowns; full-run validation is required.
