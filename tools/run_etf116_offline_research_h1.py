"""Offline, research-only ETF116 metrics candidate runner; no network/Drive/Sheets.

An A1-approved source reader must materialize a dated input JSON. This CLI
neither fetches a provider nor asserts authenticity of supplied raw hashes.
Metrics are PREPARED_ONLY, never PIT admission/ER/BUY/ranking authority.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from tools.etf116_research_metrics_h1 import compute_horizons, canonical_hash, RefuseInput

from tools.etf116_eod_gate import validate_universe, EXPECTED_UNIVERSE_SHA256


def run(input_path: Path, frozen_path: Path, out_path: Path):
    frozen=validate_universe(frozen_path.read_text(encoding='utf-8').splitlines())
    source_bytes=input_path.read_bytes()
    input_obj=json.loads(source_bytes)
    if input_obj.get('schema')!='etf116-metrics-candidate-input-v1':
        raise RefuseInput('OFFLINE_INPUT_SCHEMA')
    if input_obj.get('scope_sha256')!=EXPECTED_UNIVERSE_SHA256:
        raise RefuseInput('OFFLINE_FROZEN_SCOPE_HASH')
    session=input_obj.get('session');decision_at=input_obj.get('decision_at_utc')
    official_calendar=input_obj.get('verified_nyse_sessions')
    if not isinstance(official_calendar,list):
        raise RefuseInput('NYSE_SESSIONS_REQUIRED')
    if not isinstance(input_obj.get('source_candidate_rows'),dict):
        raise RefuseInput('SOURCE_ROWS_NOT_MAP')
    candidates=input_obj['source_candidate_rows']
    rf=input_obj.get('risk_free_rows')
    bench=candidates.get('SPY')
    issuer_dates=input_obj.get('issuer_verified_exchange_listed_date',{})
    if not isinstance(issuer_dates,dict): raise RefuseInput('INCEPTION_MAP_INVALID')
    if any(t not in frozen for t in candidates):
        raise RefuseInput('OUT_OF_PINNED_UNIVERSE_SOURCE')
    if any(t not in frozen for t in issuer_dates):
        raise RefuseInput('OUT_OF_PINNED_UNIVERSE_ISSUER')
    status={}
    for ticker in frozen:
        try:
            status[ticker]=compute_horizons(
                ticker=ticker,asof=session,decision_at=decision_at,
                official_sessions=official_calendar,tr_rows=candidates.get(ticker,[]),
                issuer_listing_date=issuer_dates.get(ticker),rf_rows=rf,
                benchmark_rows=bench if ticker!='SPY' else None,
                benchmark_present=ticker!='SPY' and 'SPY' in candidates,
                source_rights_verified=False,benchmark_source_rights_verified=False)
        except RefuseInput as exc:
            status[ticker]={'ticker':ticker,'state':'BLOCKED_RESEARCH_INPUT',
                            'reason':str(exc),'source_rights_verified':False,
                            'a1_source_admitted':False,'rank_promotion':False}
    output={'schema':'etf116-metrics-candidate-output-v1','session':session,
            'universe_sha256':EXPECTED_UNIVERSE_SHA256,
            'source_input_bytes_sha256':hashlib.sha256(source_bytes).hexdigest(),
            'research_status':'PREPARED_ONLY_NO_AUTHORITY',
            'source_rights_verified':False,
            'allowed_for_sheet_publisher':False,'a1_pit_admitted':False,
            'eligible_for_er_buy':False,'eligible_for_target':False,
            'economic_authority':False,
            'verified_research_window_count':sum(r.get('data_complete_windows',0) for r in status.values()),
            'blocked_tickers':sum(not r.get('data_complete_windows',0) for r in status.values()),
            'ticker_results':status}
    output['candidate_receipt_sha256']=canonical_hash(output)
    out_path.parent.mkdir(parents=True,exist_ok=True)
    if out_path.exists():raise RefuseInput('NO_OVERWRITE_EXISTING_CANDIDATE')
    with out_path.open('x', encoding='utf-8') as handle:
        handle.write(json.dumps(output,indent=2,sort_keys=True,allow_nan=False)+'\n')
    return {'session':session,'tickers':len(frozen),'blocked_tickers':output['blocked_tickers'],
            'verified_research_windows':output['verified_research_window_count'],
            'source_rights_verified':False,'economic_authority':False}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',required=True);p.add_argument('--frozen',required=True)
    p.add_argument('--output',required=True)
    a=p.parse_args()
    print(json.dumps(run(Path(a.input),Path(a.frozen),Path(a.output)),sort_keys=True))

if __name__=='__main__':main()
