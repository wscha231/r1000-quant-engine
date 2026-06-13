# Data Coverage Gate — Lockdown Runbook

The data-first program added two always-on instruments and repaired three feeds.
This runbook is the **Step 6 lockdown**: how to flip each coverage layer from
warn-only to hard-fail once a live rebuild proves it, so green-but-empty can
never silently return.

## Instruments (always on, every full rebuild)

| Tool | Output | Role |
|---|---|---|
| `tools/build_data_catalog.py` | `data/catalog.json` | Inventory + freshness for every data store (missing / empty / stale / ok). |
| `tools/data_coverage_gate.py` | `outputs/coverage_gate.json` | Hard-fail enforcer on materialised coverage, PIT lookahead, readiness blockers. |

Both run in `full_rebuild_manual.yml` (step "Data health"). The gate currently
runs `--no-fail` with these layers downgraded to warn:

```
--warn-only etf,sec_v1_evidence,smart_money,13f,top_manager
```

## Layers and their floors

| Layer | Source key (`sec_enriched_candidate_replay/summary.json`) | Floor | Meaning |
|---|---|---|---|
| `etf` | `coverage_etf_ratio` | 0.30 | Rows with ETF holdings evidence. Was **0.0** (today-stamped snapshot). |
| `sec_v1_evidence` | `coverage_ratio` | 0.20 | Form4 v1 leader-onset hit rate (naturally sparse). |
| `13f` | `coverage_13f_ratio` | 0.50 | Rows with 13F evidence. Healthy (~0.78). |
| `smart_money` | `coverage_smart_money_ratio` | 0.50 | Smart-money shadow score. Healthy (~0.73). |
| `top_manager` | `coverage_top_manager_ratio` | 0.05 | Top-7 manager discovery lane. Was **absent** (lane unwired). |
| `pit_no_future_available_from` | readiness `pit_available_from_check` | hard | Any future-dated stamp = lookahead leak. Always hard-fail. |
| `readiness_blockers` | readiness `blockers` | hard | Missing/future price-cache manifest end, PIT gaps. Always hard-fail. |

## Flip procedure (per layer)

The repairs are landed in code but populating real data needs live runs. Flip a
layer to hard-fail **only after a rebuild proves it**, one layer at a time:

1. **ETF** — dispatch `etf_holdings_monthly_refresh.yml` (now builds the N-PORT
   historical PIT series and merges into `etf_holdings.parquet`). Then run a
   full rebuild. Confirm `coverage_etf_ratio >= 0.30` in the rebuild's
   `sec_enriched_candidate_replay/summary.json`. Remove `etf` from `--warn-only`.

2. **top_manager** — a full rebuild now builds
   `top_manager_discovery_signals.parquet` before SEC enrichment. Confirm
   `coverage_top_manager_ratio >= 0.05`. Remove `top_manager` from `--warn-only`.

3. **13f / smart_money** — already above floor historically; remove from
   `--warn-only` once one rebuild confirms they remain so with the new wiring.

4. **sec_v1_evidence** — keep warn-only or lower the floor; this is a naturally
   sparse onset detector, not a dead feed. Do not hard-fail on sparsity alone.

5. When all dead feeds are proven, drop `--no-fail` from the workflow step so the
   gate blocks the rebuild on any regression. The two hard layers
   (`pit_no_future_available_from`, `readiness_blockers`) already fail regardless
   of `--warn-only`; `--no-fail` is the only thing suppressing the exit code
   today.

## Quick local check

```bash
python3 tools/build_data_catalog.py --print-summary
python3 tools/data_coverage_gate.py --run-dir outputs --no-fail   # report-only
python3 tools/data_coverage_gate.py --run-dir outputs             # enforce (exit 1 on FAIL)
```

## Do NOT

- Do not flip a layer to hard-fail on the strength of the offline smoke tests
  alone — they prove the machinery, not that the live feed populated.
- Do not interpret a passing gate as production validity on its own; the
  AlphaOps data contract (`docs/ALPHAOPS_DATA_SYSTEM_CONTRACT.md`) still governs
  CAGR/MDD acceptance.
