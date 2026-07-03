# Dataset Coverage Audit

- latest run: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs`
- scored latest rows: 741
- latest scored date: 2026-07-02
- historical candidate rows: 47434
- historical candidate tickers: 981
- historical months: 85
- historical candidate last date: 2026-05-29
- SEC-enriched candidate present: True
- SEC-enriched candidate rows: 47434

## Universe Source

- `current_constituents_proxy_static_seed`: 44580
- `adr_whitelist`: 1399
- `current_constituents_proxy_static_seed+strategic_global_hardware`: 1202
- `cycle_play_whitelist`: 253

## Evidence Utilization

- rows with SEC evidence: 5780
- rows with 13F evidence: 36919
- rows with ETF evidence: 0
- rows with smart-money evidence: 34731
- coverage ratio: 12.2%
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
- `historical_candidate_book.ocf_growth_yoy` numeric=5.8%, nonzero=5.8%
- `historical_candidate_book.roe_proxy` numeric=45.0%, nonzero=45.0%
- `historical_candidate_book.gross_profit_ttm` numeric=45.1%, nonzero=45.1%
- `historical_candidate_book.capex_ttm` numeric=47.1%, nonzero=47.0%
- `historical_candidate_book.ocf_ttm` numeric=56.7%, nonzero=56.7%
- `historical_candidate_book.op_income_ttm` numeric=57.0%, nonzero=57.0%
- `historical_candidate_book.revenues_ttm` numeric=57.9%, nonzero=57.9%

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

- `AMAT`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=85; sleeve=`core_compounder`; score=7.927483245803956
- `AMD`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=73; sleeve=`core_compounder`; score=6.95378005493635
- `ANET`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=55; sleeve=`core_compounder`; score=2.276785605932974
- `ARM`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`core_compounder`; score=4.0791095421830645
- `ASML`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`core_compounder`; score=5.399202465268863
- `AVGO`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=85; sleeve=`core_compounder`; score=2.3581593374584715
- `CIEN`: selection_gate_or_rank_rejected; latest=True; hist_months=85; sleeve=`unassigned`; score=1.8315494392443932
- `COHR`: selection_gate_or_rank_rejected; latest=True; hist_months=23; sleeve=`unassigned`; score=3.3433827437687875
- `DELL`: selection_gate_or_rank_rejected; latest=True; hist_months=7; sleeve=`unassigned`; score=5.648320944754608
- `GEV`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=11; sleeve=`core_compounder`; score=5.649375261135502
- `GLW`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=11; sleeve=`future_winner`; score=5.952960147154522
- `GOOGL`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=85; sleeve=`core_compounder`; score=5.40726125855117
- `HPE`: selection_gate_or_rank_rejected; latest=True; hist_months=85; sleeve=`unassigned`; score=5.190661680316228
- `INTC`: historical_only_not_current_latest_universe; latest=False; hist_months=63; sleeve=``; score=None
- `KLAC`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=82; sleeve=`early_scout`; score=6.981044972699228
- `LITE`: selection_gate_or_rank_rejected; latest=True; hist_months=73; sleeve=`unassigned`; score=3.3138055941316718
- `LRCX`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=85; sleeve=`core_compounder`; score=7.793232554242792
- `MRVL`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=51; sleeve=`future_winner`; score=6.070586375153
- `MU`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=85; sleeve=`core_compounder`; score=5.721081334080266
- `NVDA`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=67; sleeve=`core_compounder`; score=4.837212747248296
- `OKLO`: historical_only_not_current_latest_universe; latest=False; hist_months=6; sleeve=``; score=None
- `PLTR`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=29; sleeve=`core_compounder`; score=4.490948784704061
- `QCOM`: selection_gate_or_rank_rejected; latest=True; hist_months=85; sleeve=`unassigned`; score=3.053562427953416
- `SMCI`: historical_only_not_current_latest_universe; latest=False; hist_months=8; sleeve=``; score=None
- `SMR`: historical_only_not_current_latest_universe; latest=False; hist_months=6; sleeve=``; score=None
- `SNDK`: selection_gate_or_rank_rejected; latest=True; hist_months=4; sleeve=`unassigned`; score=6.37357902739042
- `STX`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`future_winner`; score=5.143192506812223
- `TSM`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`core_compounder`; score=4.53713412247907
- `VRT`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=50; sleeve=`core_compounder`; score=4.841533606369859
- `WDC`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=40; sleeve=`future_winner`; score=6.877710412092686
- `WMT`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=25; sleeve=`core_compounder`; score=2.452768522401181

## Files

- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit.json`
- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit_coverage.csv`
- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit_watchlist.csv`
- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit_distributions.csv`
