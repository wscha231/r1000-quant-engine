# Dataset Coverage Audit

- latest run: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs`
- scored latest rows: 746
- latest scored date: 2026-05-15
- historical candidate rows: 38098
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
- `historical_candidate_book.op_income_growth_yoy` numeric=3.6%, nonzero=3.6%
- `historical_candidate_book.ocf_growth_yoy` numeric=3.6%, nonzero=3.6%
- `historical_candidate_book.roe_proxy` numeric=41.7%, nonzero=41.7%
- `historical_candidate_book.gross_profit_ttm` numeric=42.3%, nonzero=42.3%
- `historical_candidate_book.capex_ttm` numeric=44.6%, nonzero=44.5%
- `historical_candidate_book.ocf_ttm` numeric=54.2%, nonzero=54.2%
- `historical_candidate_book.op_income_ttm` numeric=54.4%, nonzero=54.4%
- `historical_candidate_book.revenues_ttm` numeric=55.4%, nonzero=55.4%

## Missing Audit Columns

- `historical_candidate_book.r_12m`
- `historical_candidate_book.r_6m`
- `latest_scored.eps_revision_proxy`
- `latest_scored.revision_score`

## Watchlist Gaps

- `AMAT`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`core_compounder`; score=4.069210878932708
- `AMD`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`core_compounder`; score=4.41073600186683
- `ANET`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`core_compounder`; score=2.0422303631391383
- `ARM`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`future_winner`; score=4.069592256513754
- `ASML`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`core_compounder`; score=3.620830523515561
- `AVGO`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`core_compounder`; score=2.447743576975832
- `CIEN`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`future_winner`; score=3.066263555693161
- `COHR`: selection_gate_or_rank_rejected; latest=True; hist_months=0; sleeve=`unassigned`; score=3.094646933932036
- `DELL`: not_in_latest_universe; latest=False; hist_months=0; sleeve=``; score=None
- `GEV`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=9; sleeve=`core_compounder`; score=5.458748389814385
- `GLW`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`future_winner`; score=4.793509413813913
- `GOOGL`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=83; sleeve=`core_compounder`; score=5.5099246091283645
- `HPE`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`early_scout`; score=2.043120986266919
- `INTC`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`core_compounder`; score=2.1785724694885835
- `KLAC`: selection_gate_or_rank_rejected; latest=True; hist_months=0; sleeve=`unassigned`; score=4.23383080331879
- `LITE`: selection_gate_or_rank_rejected; latest=True; hist_months=0; sleeve=`unassigned`; score=4.093559075863363
- `LRCX`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`core_compounder`; score=3.678674053227307
- `MRVL`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`future_winner`; score=4.475965976726786
- `MU`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`core_compounder`; score=2.226016946298014
- `NVDA`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`core_compounder`; score=4.047041543002574
- `OKLO`: historical_only_not_current_latest_universe; latest=False; hist_months=6; sleeve=``; score=None
- `PLTR`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=27; sleeve=`core_compounder`; score=6.156972407313528
- `QCOM`: selection_gate_or_rank_rejected; latest=True; hist_months=0; sleeve=`unassigned`; score=4.526663017558128
- `SMCI`: selection_gate_or_rank_rejected; latest=True; hist_months=0; sleeve=`unassigned`; score=0.3651681366124539
- `SMR`: historical_only_not_current_latest_universe; latest=False; hist_months=6; sleeve=``; score=None
- `SNDK`: selection_gate_or_rank_rejected; latest=True; hist_months=0; sleeve=`unassigned`; score=2.019710547472946
- `STX`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`future_winner`; score=3.586035401241093
- `TSM`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`core_compounder`; score=4.024152182881391
- `VRT`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`core_compounder`; score=5.312352978821994
- `WDC`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`future_winner`; score=2.795420416053572
- `WMT`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=23; sleeve=`core_compounder`; score=4.412176321355455

## Files

- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit.json`
- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit_coverage.csv`
- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit_watchlist.csv`
- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit_distributions.csv`
