# AlphaOps Metric Hygiene

AlphaOps production verdicts must use broker-ledger account replay metrics.
Legacy target-weight or proxy metrics are research diagnostics only.

## Official Sources

The only production-valid performance sources are:

- `outputs/broker_replay/main/metrics.json`
- `outputs/broker_replay/concentrated/metrics.json`
- `outputs/account_evaluation/official_metrics.json`

The required official mode is `broker_ledger_next_close` with:

- next-close fills
- integer shares
- cash ledger
- transaction costs
- daily account drawdown

## Deprecated Sources

These files cannot produce SHIP verdicts:

- `outputs/backtest_metrics.json`
- `outputs/concentrated_backtest_metrics.json`
- legacy target-weight monthly returns
- proxy event metrics

They may be used for attribution or research hints only.

## Gate Modes

`run_local.py` defaults to:

```bash
python run_local.py --gate-mode broker
```

`--gate-mode target` is retained only for deprecated research comparison. It
must not be used for production promotion.

## Broker Gates

Interim production gates:

- main: CAGR `>= 30%`, MaxDD `>= -25%`
- concentrated: CAGR `>= 45%`, MaxDD `>= -25%`

Final target:

- main: CAGR `>= 30%`, MaxDD `>= -20%`
- concentrated: CAGR `>= 50%`, MaxDD `>= -25%`

Fast replay alone is `PARTIAL`. A SHIP candidate requires both fast replay and
full rebuild to pass broker-ledger gates.

## W1 Audit Commands

Validate target-book cash semantics:

```bash
python tools/validate_target_book_cash_contract.py --latest-run outputs
```

Compare a full rebuild against a fast replay:

```bash
python tools/run_fast_full_drift_audit.py --full-run <full_artifact_outputs> --fast-run <fast_artifact_outputs>
```

Explain research/proxy versus broker-ledger gaps:

```bash
python tools/run_broker_gap_attribution.py --latest-run outputs
```

Hard rejects:

- missing official broker metrics
- legacy-only SHIP verdict
- unexplained fast/full drift
- CASH contract failure
- cash trap
- OOS robustness failure
