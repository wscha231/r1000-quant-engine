# Dataset Coverage Audit

- latest run: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs`
- scored latest rows: 725
- latest scored date: 2026-05-22
- historical candidate rows: 39074
- historical months: 83
- historical candidate last date: 2026-03-31

## Effective Market Cap Coverage

- `latest_scored` effective cap numeric=100.0%, inputs=`market_cap_live,mktcap`
- `historical_candidate_book` effective cap numeric=100.0%, inputs=`market_cap_live,mktcap`

## Largest Coverage Gaps

- `historical_candidate_book.market_cap_live` numeric=0.0%, nonzero=0.0%
- `historical_candidate_book.gross_margins` numeric=0.0%, nonzero=0.0%
- `historical_candidate_book.operating_margins` numeric=0.0%, nonzero=0.0%
- `historical_candidate_book.revenue_growth_final` numeric=0.0%, nonzero=0.0%
- `historical_candidate_book.op_income_growth_yoy` numeric=3.5%, nonzero=3.5%
- `historical_candidate_book.ocf_growth_yoy` numeric=3.6%, nonzero=3.6%
- `historical_candidate_book.roe_proxy` numeric=42.1%, nonzero=42.1%
- `historical_candidate_book.gross_profit_ttm` numeric=42.8%, nonzero=42.8%
- `historical_candidate_book.capex_ttm` numeric=44.6%, nonzero=44.5%
- `historical_candidate_book.ocf_ttm` numeric=54.3%, nonzero=54.3%
- `historical_candidate_book.op_income_ttm` numeric=54.6%, nonzero=54.6%
- `historical_candidate_book.revenues_ttm` numeric=55.5%, nonzero=55.5%

## Missing Audit Columns

- `historical_candidate_book.r_12m`
- `historical_candidate_book.r_6m`
- `latest_scored.eps_revision_proxy`
- `latest_scored.revision_score`

## Watchlist Gaps

- `AMAT`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=83; sleeve=`core_compounder`; score=4.778567862872047
- `AMD`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=71; sleeve=`core_compounder`; score=6.579703838084026
- `ANET`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=53; sleeve=`core_compounder`; score=2.316356963294897
- `ARM`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`core_compounder`; score=7.493733639716751
- `ASML`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`core_compounder`; score=4.8625005063987246
- `AVGO`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=83; sleeve=`core_compounder`; score=2.714119991430445
- `CIEN`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=83; sleeve=`future_winner`; score=5.487243419766803
- `COHR`: selection_gate_or_rank_rejected; latest=True; hist_months=21; sleeve=`unassigned`; score=5.62929796757553
- `DELL`: not_in_latest_universe; latest=False; hist_months=0; sleeve=``; score=None
- `GEV`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=9; sleeve=`core_compounder`; score=5.651490228776036
- `GLW`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=10; sleeve=`future_winner`; score=5.565688515833932
- `GOOGL`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=83; sleeve=`core_compounder`; score=5.733045158816586
- `HPE`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=83; sleeve=`early_scout`; score=4.96546814523718
- `INTC`: not_in_latest_universe; latest=False; hist_months=0; sleeve=``; score=None
- `KLAC`: selection_gate_or_rank_rejected; latest=True; hist_months=83; sleeve=`unassigned`; score=4.726850184564469
- `LITE`: selection_gate_or_rank_rejected; latest=True; hist_months=71; sleeve=`unassigned`; score=5.9878304161049485
- `LRCX`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=83; sleeve=`core_compounder`; score=5.517876336605997
- `MRVL`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=49; sleeve=`future_winner`; score=6.547625804503413
- `MU`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=83; sleeve=`core_compounder`; score=6.139083499107693
- `NVDA`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=65; sleeve=`core_compounder`; score=4.528982015165446
- `OKLO`: historical_only_not_current_latest_universe; latest=False; hist_months=6; sleeve=``; score=None
- `PLTR`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=27; sleeve=`core_compounder`; score=6.478791407027126
- `QCOM`: selection_gate_or_rank_rejected; latest=True; hist_months=83; sleeve=`unassigned`; score=6.6439456857359085
- `SMCI`: not_in_latest_universe; latest=False; hist_months=0; sleeve=``; score=None
- `SMR`: historical_only_not_current_latest_universe; latest=False; hist_months=6; sleeve=``; score=None
- `SNDK`: selection_gate_or_rank_rejected; latest=True; hist_months=2; sleeve=`unassigned`; score=3.5325565041320304
- `STX`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`future_winner`; score=6.150186490150352
- `TSM`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`core_compounder`; score=4.705027406772573
- `VRT`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=48; sleeve=`core_compounder`; score=6.538776701213247
- `WDC`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=38; sleeve=`future_winner`; score=6.30868578343765
- `WMT`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=23; sleeve=`core_compounder`; score=3.8272081507077895

## Files

- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit.json`
- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit_coverage.csv`
- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit_watchlist.csv`
- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit_distributions.csv`
