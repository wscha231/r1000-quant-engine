"""Offline actual ETF top-10 research snapshot validation; never writes a seed.

This is a reusable intake adapter for tools/run_etf_holdings_refresh.py and the
A2 Registry; it does not run yfinance, initiate network I/O or publish scores.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from tools.etf116_research_backend import prepare_holdings


def run(holdings_csv: Path, *, seed_symbols: list[str], observation_at: str,
        output: Path) -> dict:
    source_bytes=holdings_csv.read_bytes()
    rows=list(csv.DictReader(io.StringIO(source_bytes.decode('utf-8'),newline='')))
    cohort=[]
    for r in rows:
        cohort.append({'etf':r['etf'],'ticker':r['ticker'],'rank':int(r['rank']),
            'weight_pct':float(r['weight_pct']),'holdings_asof':r['holdings_asof'],
            'source_url':r['source_url'],'published_at_utc':r.get('published_at_utc') or None})
    result=prepare_holdings(cohort,seed_symbols,decision_at=observation_at)
    result['source_input_bytes_sha256']=hashlib.sha256(source_bytes).hexdigest()
    result['research_only']=True
    result['sheet_publisher_allowed']=False
    output.parent.mkdir(parents=True,exist_ok=True)
    if output.exists():raise ValueError('NO_RESEARCH_ARTIFACT_OVERWRITE')
    with output.open('x', encoding='utf-8') as handle:
        handle.write(json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+'\n')
    return {k:result[k] for k in ['holding_slots','unique_securities','count_already_in_seed',
                                   'provenance_time_complete','eligible_for_pit','universe_seed_modified']}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--holdings',required=True)
    p.add_argument('--seed-tickers',required=True,help='Existing actual frozen 1009 ticker-list (not modified)')
    p.add_argument('--observed-at',required=True)
    p.add_argument('--output',required=True)
    a=p.parse_args()
    seed=Path(a.seed_tickers).read_text(encoding='utf-8').splitlines()
    print(json.dumps(run(Path(a.holdings),seed_symbols=seed,observation_at=a.observed_at,
                         output=Path(a.output)),sort_keys=True))

if __name__=='__main__':main()
