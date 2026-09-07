#!/usr/bin/env python3
"""Bounded read-only-source CLI checks. Synthetic connection is not profitability.

Run from the US repo with the pinned research dependencies and --kr-root.
Writes only independent outputs/research_decision_v1 folders in each repo.
"""
import sys
if __name__ == "__main__" and not sys.flags.isolated:
    print("BLOCKED_RUNTIME: invoke with python -I from the pinned research environment", file=sys.stderr)
    raise SystemExit(2)
import argparse
import copy
import hashlib
import json
import math
import subprocess
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


def verify_case(label, first, second, before, after, report):
    """Receipt gates remain active under -O and PYTHONOPTIMIZE."""
    if first['result']['decision_hash'] != second['result']['decision_hash'] or before != after:
        raise ValueError('connection_repeat_not_identical')
    proposal = report['portfolio_proposal']
    weights = [r['target_weight'] for r in proposal['rows']] + [proposal['cash_weight']]
    if any(type(w) not in (int, float) or not math.isfinite(w) or not 0 <= w <= 1 for w in weights):
        raise ValueError('connection_invalid_weight')
    total = sum(weights)
    if not math.isclose(total, 1., rel_tol=0., abs_tol=1e-10): raise ValueError('connection_weight_sum')
    expected_kind = {'REAL_PILOT': 'REAL', 'SYNTHETIC_3': 'SYNTHETIC', 'SYNTHETIC_7': 'SYNTHETIC'}.get(label)
    if expected_kind is None or report['data_kind'] != expected_kind: raise ValueError('connection_data_kind')
    readiness = report['readiness']
    if readiness['orders_allowed'] is not False or readiness['oos_validated'] is not False:
        raise ValueError('connection_unearned_readiness')
    if label == 'REAL_PILOT' and readiness['portfolio_proposal_ready'] is not False:
        raise ValueError('frozen_real_pilot_unexpectedly_ready')
    if label == 'SYNTHETIC_7' and readiness['target_5_plus_2_complete'] is not True:
        raise ValueError('connection_fixture_5_plus_2_incomplete')
    return total


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
            us_path, kr_path, ctx_path = evidence/'us_pilot_input.json', evidence/'kr_pilot_input.json', evidence/'context_v2.json'
            expected = 2
        else:
            us_input, kr_input, ctx = fixture_set('US', counts[0]), fixture_set('KR', counts[1]), context()
            base = research_root(ROOT) / 'synthetic_inputs' / label / digest([us_input, kr_input, ctx])
            us_path = immutable_json(base/'us.json', us_input)
            kr_path = immutable_json(base/'kr.json', kr_input)
            ctx_path = immutable_json(base/'context.json', ctx)
            expected = 0
        us = run([sys.executable, '-I', 'tools/export_research_decision_market.py', '--input', str(us_path)], ROOT, expected)
        kr = run([sys.executable, '-I', 'tools/export_research_decision_market.py', '--input', str(kr_path),
                  '--engine-root', str(ROOT), '--engine-source-hash', source_hash], kr_root, expected)
        command = [sys.executable, '-I', 'tools/run_research_decision_v1.py', '--market-export', us['result']['path'],
                   '--market-export', kr['result']['path'], '--context', str(ctx_path)]
        first = run(command, ROOT, expected)
        directory = Path(first['result']['directory'])
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.iterdir() if p.is_file()}
        second = run(command, ROOT, expected)
        after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.iterdir() if p.is_file()}
        report = json.loads((directory/'report.json').read_text())
        proposal = report['portfolio_proposal']
        total = verify_case(label, first, second, before, after, report)
        checks['cases'][label] = {'exports': {'US': us, 'KR': kr}, 'first': first, 'repeat': second,
                                 'identical_decision_and_files': True, 'file_sha256': before,
                                 'weights_plus_cash': total, 'cash_weight': proposal['cash_weight'],
                                 'rows': proposal['rows'], 'readiness': report['readiness'],
                                 'real_expansion_allowed': False if counts is None else None}
    path = immutable_json(research_root(ROOT)/'verification'/('connection_'+checks['source_commit']+'.json'), checks)
    print(json.dumps({'verification': str(path), 'cases': {k: v['first']['result'] for k,v in checks['cases'].items()}}, sort_keys=True))


if __name__ == '__main__': main()
