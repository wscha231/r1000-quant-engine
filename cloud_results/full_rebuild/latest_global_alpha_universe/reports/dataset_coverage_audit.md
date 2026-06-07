# Dataset Coverage Audit

- latest run: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs`
- scored latest rows: 739
- latest scored date: 2026-06-05
- historical candidate rows: 46781
- historical candidate tickers: 969
- historical months: 84
- historical candidate last date: 2026-04-30
- SEC-enriched candidate present: True
- SEC-enriched candidate rows: 46781

## Universe Source

- `current_constituents_proxy_static_seed`: 43976
- `adr_whitelist`: 1370
- `current_constituents_proxy_static_seed+strategic_global_hardware`: 1187
- `cycle_play_whitelist`: 248

## Evidence Utilization

- rows with SEC evidence: 5622
- rows with 13F evidence: 36409
- rows with ETF evidence: 0
- rows with smart-money evidence: 34265
- coverage ratio: 12.0%
- 13F coverage ratio: 77.8%

## Effective Market Cap Coverage

- `latest_scored` effective cap numeric=100.0%, inputs=`market_cap_live,mktcap`
- `historical_candidate_book` effective cap numeric=100.0%, inputs=`market_cap_live,mktcap`

## Largest Coverage Gaps

- `historical_candidate_book.market_cap_live` numeric=0.0%, nonzero=0.0%
- `historical_candidate_book.gross_margins` numeric=0.0%, nonzero=0.0%
- `historical_candidate_book.operating_margins` numeric=0.0%, nonzero=0.0%
- `historical_candidate_book.revenue_growth_final` numeric=0.0%, nonzero=0.0%
- `historical_candidate_book.op_income_growth_yoy` numeric=5.2%, nonzero=5.2%
- `historical_candidate_book.ocf_growth_yoy` numeric=5.9%, nonzero=5.9%
- `historical_candidate_book.roe_proxy` numeric=44.8%, nonzero=44.8%
- `historical_candidate_book.gross_profit_ttm` numeric=44.9%, nonzero=44.9%
- `historical_candidate_book.capex_ttm` numeric=46.9%, nonzero=46.8%
- `historical_candidate_book.ocf_ttm` numeric=56.4%, nonzero=56.4%
- `historical_candidate_book.op_income_ttm` numeric=56.8%, nonzero=56.8%
- `historical_candidate_book.revenues_ttm` numeric=57.6%, nonzero=57.6%

## Missing Audit Columns

- `historical_candidate_book.available_from`
- `historical_candidate_book.early_evidence_score`
- `historical_candidate_book.etf_holdings_score`
- `historical_candidate_book.etf_theme_leadership_score`
- `historical_candidate_book.evidence_fusion_score`
- `historical_candidate_book.institutional_evidence_score`
- `historical_candidate_book.latest_13f_available_from`
- `historical_candidate_book.latest_available_from`
- `historical_candidate_book.latest_etf_available_from`
- `historical_candidate_book.leader_onset_sec_v3_score`
- `historical_candidate_book.r_12m`
- `historical_candidate_book.r_6m`
- `historical_candidate_book.sec_13f_score`
- `historical_candidate_book.sec_13f_smart_money_score`
- `historical_candidate_book.sec_combined_evidence_score`
- `historical_candidate_book.sec_form4_score`

## Watchlist Gaps

- `AMAT`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`core_compounder`; score=6.982101492884866
- `AMD`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=72; sleeve=`core_compounder`; score=6.197568640214469
- `ANET`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=54; sleeve=`core_compounder`; score=2.981830935981734
- `ARM`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`core_compounder`; score=6.328230396035583
- `ASML`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`core_compounder`; score=5.425867240704963
- `AVGO`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`core_compounder`; score=2.4398275763595616
- `CIEN`: selection_gate_or_rank_rejected; latest=True; hist_months=84; sleeve=`unassigned`; score=3.9889662945476414
- `COHR`: selection_gate_or_rank_rejected; latest=True; hist_months=22; sleeve=`unassigned`; score=5.341402073239177
- `DELL`: historical_only_not_current_latest_universe; latest=False; hist_months=7; sleeve=``; score=None
- `GEV`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=10; sleeve=`core_compounder`; score=3.531008977625053
- `GLW`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=10; sleeve=`future_winner`; score=6.239851233863134
- `GOOGL`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`core_compounder`; score=5.214505467533545
- `HPE`: selection_gate_or_rank_rejected; latest=True; hist_months=84; sleeve=`unassigned`; score=7.967483764163215
- `INTC`: historical_only_not_current_latest_universe; latest=False; hist_months=63; sleeve=``; score=None
- `KLAC`: selection_gate_or_rank_rejected; latest=True; hist_months=84; sleeve=`unassigned`; score=6.105345264877885
- `LITE`: selection_gate_or_rank_rejected; latest=True; hist_months=72; sleeve=`unassigned`; score=5.693038628860459
- `LRCX`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`core_compounder`; score=7.586259453118661
- `MRVL`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=50; sleeve=`future_winner`; score=6.086253894821118
- `MU`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`core_compounder`; score=6.3713199650088495
- `NVDA`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=66; sleeve=`core_compounder`; score=5.101818928580643
- `OKLO`: historical_only_not_current_latest_universe; latest=False; hist_months=6; sleeve=``; score=None
- `PLTR`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=28; sleeve=`core_compounder`; score=3.8568668527092793
- `QCOM`: selection_gate_or_rank_rejected; latest=True; hist_months=84; sleeve=`unassigned`; score=5.436551901451375
- `SMCI`: historical_only_not_current_latest_universe; latest=False; hist_months=8; sleeve=``; score=None
- `SMR`: historical_only_not_current_latest_universe; latest=False; hist_months=6; sleeve=``; score=None
- `SNDK`: selection_gate_or_rank_rejected; latest=True; hist_months=3; sleeve=`unassigned`; score=5.403820681949654
- `STX`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`future_winner`; score=6.395397978993207
- `TSM`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`core_compounder`; score=4.920389188972555
- `VRT`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=49; sleeve=`core_compounder`; score=4.1138601233008645
- `WDC`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=39; sleeve=`future_winner`; score=7.09467407492474
- `WMT`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=24; sleeve=`core_compounder`; score=3.1348852082103797

## Files

- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit.json`
- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit_coverage.csv`
- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit_watchlist.csv`
- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit_distributions.csv`
