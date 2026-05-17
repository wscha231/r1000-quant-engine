# Agent Contracts 20260516

## Global Rules

- Each agent solves one problem only.
- Every strategy claim must state whether it is official or research-only.
- Production defaults cannot change without human approval.
- Research outputs must include `research_only=true` and `production_activation_allowed=false` where machine-readable metadata is written.
- Challenger outputs must be isolated under dedicated output directories and must not overwrite default `outputs/broker_replay/main` or `outputs/broker_replay/concentrated`.

## Agent Scopes

| Agent | Role | Allowed Focus | Forbidden |
| --- | --- | --- | --- |
| A0 Orchestrator | Control plane | `research/multi_agent_operating_plan_20260516/` | Strategy code, production defaults |
| A1 Data/PIT | Data reliability | CIK schema, PIT coverage, dataset audit | Scoring weights |
| A2 SEC Evidence | Filing-event evidence | Form 4, then 13D/G, 8-K, 13F, Form 144 | Direct production scoring |
| A3 Selection | Shadow scoring | `early_evidence_score`, `leader_onset_score`, report-only IC | `score_total` activation |
| A4 Main PM | Main portfolio | Main challenger target books and isolated broker replay | Concentrated defaults |
| A5 Concentrated PM | Concentrated portfolio | N2/N3/N5 challengers, staged entry, caps | N7 champion promotion without official pass |
| A6 Broker/Risk | Account replay | broker-ledger, cost sensitivity, stress, replacement replay | Proxy-only promotion |
| A7 Diagnostics | Attribution | run diff, hold-vs-replace, missed leaders | Strategy activation |
| A8 QA/Governance | Safety gate | leakage/PIT/schema/label tests | Changing strategy logic |
| A9 DevOps | Workflows | sidecar split, timing reports, artifact guards | Metric interpretation |

## Conflict Control

High-conflict files:

```text
r1000_pipeline.py
r1000_signals.py
r1000_config.py
tools/build_operating_target_books.py
tools/run_account_evaluation.py
```

Only one implementation agent may own a high-conflict file in a given PR series. Other agents must work in isolated tools, tests, or research outputs.

## SEC Evidence Contract

Form 4 MVP writes only:

```text
data_pit/sec/sec_filings_index.parquet
data_pit/sec/form4_transactions.parquet
outputs/sec_ownership_signals/form4_latest.csv
outputs/sec_ownership_signals/ownership_signal_summary.json
outputs/sec_ownership_signals/report.md
```

Required PIT fields:

```text
accepted_at
available_from
filing_date
accession_number
cik10 as 10-character string
```

`transaction_date` must never be used as feature availability.
