#!/usr/bin/env python3
"""Read current research evidence and publish a strictly allowlisted site view.

No source file, raw report, account, artifact extraction, or mutable target is
published. Existing monitor verifies exact workflow/run/artifact/score lineage.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools.run_run287_daily_research_monitor import (
    CONTRACT, GitHub, collect_source, completed_session, date_state, evaluate,
    latest_run, number,
)

SCHEMA = 'run287-public-project-results-v1'
REPO = 'wscha231/r1000-quant-engine'
SOURCE_LABELS = {'operating': '종목 평가·포트폴리오', 'tactical': '장 마감·산업 분석',
                 'estimates': '실적·추정치', 'ownership': '기관 공시', 'history': '장기 재무·거시 자료'}
STATUSES = {'MISSING_RUN', 'UPSTREAM_IN_PROGRESS', 'UPSTREAM_FAILED', 'MISSING_ARTIFACT',
            'MISSING_CONTRACT_MEMBERS', 'VERIFIED_ARTIFACT', 'BLOCKED_SOURCE',
            'WORKFLOW_SUCCESS_DATA_UNVERIFIED'}


def day(value):
    return value if isinstance(value, str) and date_state(value, '2000-01-01') not in {'MISSING_OR_INVALID_DATE'} else None


def sha(value):
    return value if isinstance(value, str) and re.fullmatch('[a-f0-9]{40}|[a-f0-9]{64}', value) else None


def integer(value):
    return value if type(value) is int and 0 <= value <= 10**12 else None


def positive_close(value):
    value = number(value)
    return value is not None and value > 0


def source_view(key, source):
    run = source.get('run') or {}
    run_id = integer(run.get('id'))
    artifact = source.get('artifact') or {}
    return {'key': key, 'label': SOURCE_LABELS[key],
            'status': source.get('status') if source.get('status') in STATUSES else 'BLOCKED_SOURCE',
            'run_id': run_id, 'run_url': f'https://github.com/{REPO}/actions/runs/{run_id}' if run_id else None,
            'commit': sha(run.get('head_sha')), 'artifact_id': integer(artifact.get('id')),
            'artifact_verified': source.get('artifact_hash_verified') is True,
            'artifact_sha256': sha(str(artifact.get('digest', '')).removeprefix('sha256:'))}


def build(report, sources, session, now, code_sha, contract_hash):
    if report.get('schema_version') != 'run287-daily-research-monitor-v1' or report.get('repository') != REPO:
        raise ValueError('invalid_research_report')
    safety = report.get('safety', {})
    if safety.get('research_only') is not True or any(safety.get(k) is not False for k in
            ['orders_allowed', 'target_book_write_allowed', 'ledger_write_allowed', 'production_activation_allowed']):
        raise ValueError('invalid_research_safety')
    rows, seen = [], set()
    report_current = report.get('expected_us_session') == session
    for row in report.get('watchlist', []):
        ticker = row.get('ticker')
        market = row.get('market')
        if market not in {'US', 'KR'} or not isinstance(ticker, str) or not re.fullmatch(r'[A-Z0-9.\-]{1,12}', ticker):
            raise ValueError('invalid_public_identity')
        if (market, ticker) in seen:
            raise ValueError('duplicate_public_identity')
        seen.add((market, ticker))
        score_current = report_current and report.get('current_engine_scores_ready') is True and row.get('engine_score_as_of') == session
        score = number(row.get('current_engine_score')) if score_current else None
        price_current = report_current and row.get('price_status') == 'CURRENT' and row.get('price_as_of') == session
        price = number(row.get('close')) if price_current else None
        rows.append({'ticker': ticker, 'market': market, 'close': price if price and price > 0 else None,
                     'price_as_of': day(row.get('price_as_of')), 'engine_score': score,
                     'score_as_of': day(row.get('engine_score_as_of')),
                     'status': ('KR_ADAPTER_REQUIRED' if market == 'KR' else
                                'CURRENT_NONRANKING_DIAGNOSTIC' if score is not None else 'SCORE_UNAVAILABLE'),
                     'eligible': row.get('engine_research_eligible') is True if score is not None else False,
                     'quarantined': row.get('engine_corporate_action_quarantine') is True})
    tactical = sources.get('tactical', {})
    # Failed producer artifacts can explain a failure, never supply active data.
    data = tactical.get('data', {}) if tactical.get('status') == 'VERIFIED_ARTIFACT' else {}
    theme = data.get('theme', {})
    macro = data.get('macro', {})
    etfs = data.get('etfs', {}).get('etfs', {})
    theme_date = day(theme.get('latest_price_date'))
    theme_safe = theme.get('research_only') is True and theme.get('production_activation_allowed') is False
    diagnostics = {
        'theme': {'data_as_of': theme_date if theme_safe else None,
                  'status': date_state(theme_date, session) if theme_safe else 'UNAVAILABLE',
                  'scored_count': integer(theme.get('tickers_scored')) if theme_safe else None,
                  'liquid_count': integer(theme.get('liquid_tickers')) if theme_safe else None},
        # These legacy exporters expose collection dates, not observation dates.
        # Even finite numbers cannot certify current macro/ETF observations.
        'macro': {'collection_date': day(macro.get('asof_date')), 'status': 'OBSERVATION_DATES_UNVERIFIED',
                  'price_present': positive_close(macro.get('spy_close'))},
        'etfs': {'collection_date': day(data.get('etfs', {}).get('asof_date')),
                 'status': 'OBSERVATION_DATES_UNVERIFIED', 'total': len(etfs) if isinstance(etfs, dict) else 0,
                 'finite_close_count': sum(positive_close(v.get('close')) for v in etfs.values() if isinstance(v, dict)) if isinstance(etfs, dict) else 0}}
    result = {'schema_version': SCHEMA, 'review_only': True, 'live_trading_enabled': False,
              'generated_at': now.isoformat(), 'expected_us_session': session,
              'source_commit': sha(code_sha), 'config_hash': sha(contract_hash),
              'scope': 'EXISTING_RESEARCH_WATCHLIST_NOT_FULL_UNIVERSE',
              'ranking_ready': False, 'sources': [source_view(k, v) for k, v in sources.items() if k in SOURCE_LABELS],
              'rows': rows, 'diagnostics': diagnostics}
    # Deterministic content identity; intentionally excludes its own hash.
    result['data_hash'] = hashlib.sha256(json.dumps(result, sort_keys=True, allow_nan=False).encode()).hexdigest()
    return result


def collect_history(client, workflow_path=ROOT/'.github/workflows/long_history_research.yml'):
    # The optional producer is under review in PR420. Do not invent an outage
    # until its workflow is installed on the checked-out trusted master.
    if not workflow_path.is_file():
        return None
    history = {'status': 'MISSING_RUN'}
    try:
        runs = client.json('/actions/workflows/long_history_research.yml/runs?branch=master&per_page=30')
        run = latest_run(runs.get('workflow_runs', []), 'long_history_research.yml', REPO, ['push','schedule','workflow_dispatch'])
        if run:
            history = {'run': run, 'status': 'UPSTREAM_IN_PROGRESS' if run.get('status') != 'completed' else
                       'WORKFLOW_SUCCESS_DATA_UNVERIFIED' if run.get('conclusion') == 'success' else 'UPSTREAM_FAILED'}
    except Exception:
        history = {'status': 'BLOCKED_SOURCE'}
    return history


def collect(now):
    contract = json.loads(CONTRACT.read_text())
    spec = contract['sources']['tactical']
    extras = {'macro': 'cloud_results/macro_daily/latest.json',
              'etfs': 'cloud_results/etf_leadership/latest.json',
              'theme': 'cloud_results/theme_leadership_tape/summary.json'}
    spec['members'].update(extras)
    spec['optional_members'] = list(extras)
    client = GitHub(REPO, os.environ.get('GH_TOKEN', ''))
    def one(item):
        key, spec = item
        return key, collect_source(client, key, spec, contract)
    with ThreadPoolExecutor(max_workers=4) as pool:
        sources = dict(pool.map(one, contract['sources'].items()))
    session = completed_session(now)
    report = evaluate(sources, session, now, contract)
    history = collect_history(client)
    if history is not None:
        sources['history'] = history
    code_sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    config_hash = hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest()
    return build(report, sources, session, now, code_sha, config_hash)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'docs/public/data/project-results.json')
    args = parser.parse_args()
    result = collect(datetime.now(timezone.utc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.output.with_suffix('.tmp')
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
    tmp.replace(args.output)
    print(json.dumps({'public_results': 'written', 'session': result['expected_us_session'], 'rows': len(result['rows'])}))


if __name__ == '__main__':
    main()
