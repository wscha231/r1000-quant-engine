#!/usr/bin/env python3
"""Bounded read-only-source CLI checks. Synthetic connection is not profitability.

Run from the US repo with the pinned research dependencies and --kr-root.
Writes only independent outputs/research_decision_v1 folders in each repo.
"""
import argparse
import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from tools.research_decision_v1.data import canonical, digest
from tools.research_decision_v1.io import immutable_json, research_root, source_code_hash
from research_decision_v1_decision_fixture import with_scenario, context


def run(cmd, cwd, expected):
    result = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, timeout=60)
    if result.returncode != expected:
        raise RuntimeError(json.dumps({'command': cmd, 'exit': result.returncode, 'stderr': result.stderr, 'stdout': result.stdout}))
    return {'command': cmd, 'cwd': str(cwd), 'exit_code': result.returncode,
            'result': json.loads(result.stdout.strip().splitlines()[-1])}


def fixture_set(market, count):
    result = with_scenario(market)
    result['securities'] = []
    for i in range(count):
        security = copy.deepcopy(with_scenario(market)['securities'][0])
        ticker = f'FIX{i+1}' if market == 'US' else f'{990000+i:06d}'
        sid = f'{market}:{ticker}'
        security.update(ticker=ticker, security_id=sid)
        for block in security['blocks'].values(): block['security_id'] = sid
        security['blocks']['thesis']['payload']['id'] = f'fixture-{sid}'
        security['blocks']['risk']['payload']['exposures'] = {
            f'industry:synthetic-{market}-{i}': 1., f'theme:synthetic-{i}': 1., f'customer:synthetic-{i}': .4}
        for block in security['blocks'].values(): block['data_hash'] = digest(block['payload'])
        result['securities'].append(security)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kr-root', required=True)
    args = parser.parse_args()
    kr_root = Path(args.kr_root).resolve()
    source_hash = source_code_hash(ROOT)
    evidence = ROOT / 'research/decision_v1/evidence_20260907'
    checks = {'schema_version': 'research-connection-checks-v1', 'source_code_hash': source_hash,
              'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'kr_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=kr_root, text=True).strip(),
              'profitability_validated': False, 'oos_validated': False, 'cases': {}}
    for label, counts in [('REAL_PILOT', None), ('SYNTHETIC_3', (2, 1)), ('SYNTHETIC_7', (5, 2))]:
        if counts is None:
            us_path, kr_path, ctx_path = evidence/'us_pilot_input.json', evidence/'kr_pilot_input.json', evidence/'context.json'
            expected = 2
        else:
            us_input, kr_input, ctx = fixture_set('US', counts[0]), fixture_set('KR', counts[1]), context()
            base = research_root(ROOT) / 'synthetic_inputs' / label / digest([us_input, kr_input, ctx])
            us_path = immutable_json(base/'us.json', us_input)
            kr_path = immutable_json(base/'kr.json', kr_input)
            ctx_path = immutable_json(base/'context.json', ctx)
            expected = 0
        us = run([sys.executable, 'tools/export_research_decision_market.py', '--input', str(us_path)], ROOT, expected)
        kr = run([sys.executable, 'tools/export_research_decision_market.py', '--input', str(kr_path),
                  '--engine-root', str(ROOT), '--engine-source-hash', source_hash], kr_root, expected)
        command = [sys.executable, 'tools/run_research_decision_v1.py', '--market-export', us['result']['path'],
                   '--market-export', kr['result']['path'], '--context', str(ctx_path)]
        first = run(command, ROOT, expected)
        directory = Path(first['result']['directory'])
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.iterdir() if p.is_file()}
        second = run(command, ROOT, expected)
        after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.iterdir() if p.is_file()}
        assert first['result']['decision_hash'] == second['result']['decision_hash'] and before == after
        report = json.loads((directory/'report.json').read_text())
        proposal = report['portfolio_proposal']
        total = sum(r['target_weight'] for r in proposal['rows']) + proposal['cash_weight']
        assert abs(total-1.) < 1e-10
        assert report['data_kind'] == ('REAL' if counts is None else 'SYNTHETIC')
        assert not report['readiness']['orders_allowed'] and not report['readiness']['oos_validated']
        if counts is None: assert not report['readiness']['portfolio_proposal_ready']
        if counts == (5, 2): assert report['readiness']['target_5_plus_2_complete']
        checks['cases'][label] = {'exports': {'US': us, 'KR': kr}, 'first': first, 'repeat': second,
                                 'identical_decision_and_files': True, 'file_sha256': before,
                                 'weights_plus_cash': total, 'cash_weight': proposal['cash_weight'],
                                 'rows': proposal['rows'], 'readiness': report['readiness'],
                                 'real_expansion_allowed': False if counts is None else None}
    path = immutable_json(research_root(ROOT)/'verification'/('connection_'+checks['source_commit']+'.json'), checks)
    print(json.dumps({'verification': str(path), 'cases': {k: v['first']['result'] for k,v in checks['cases'].items()}}, sort_keys=True))


if __name__ == '__main__': main()
