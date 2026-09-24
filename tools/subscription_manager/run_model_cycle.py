#!/usr/bin/env python3
"""Replay reviewed internal model events into a new run; never edit parent state.

Input envelope is a trusted, prevalidated delivery/calendar adapter product. The
runner does not verify provider identity, quote economics, reviews or actual
subscriber delivery. REAL and SYNTHETIC runs remain separate. No public release.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.subscription_manager.continuous import Journal,ZERO,encode,sha,safe_path,learning_report,calibration_challenger
from tools.subscription_manager.readiness import read_pinned


def run(events_path: Path, events_hash: str, output: Path, expected_head: str,
        evaluate_at: str, train_cutoff: str, parent_path: Path|None=None, parent_hash: str|None=None):
    safe_path(output)
    if output.exists():raise ValueError('new_run_directory_required')
    envelope,_=read_pinned(events_path,events_hash)
    if set(envelope)!= {'schema','data_kind','events'} or envelope['schema']!='subscription-model-events-v1' or envelope['data_kind'] not in ('REAL','SYNTHETIC'):
        raise ValueError('events_envelope')
    if bool(parent_path)!=bool(parent_hash):raise ValueError('parent_arguments')
    parent=None
    if parent_path:
        safe_path(parent_path);parent=parent_path.read_bytes()
        if hashlib.sha256(parent).hexdigest()!=sha(parent_hash):raise ValueError('parent_hash')
    elif expected_head!=ZERO:raise ValueError('genesis_head')
    output.mkdir(parents=True);work=output/'working.sqlite'
    if parent is not None:work.write_bytes(parent)
    journal=Journal(work)
    if journal.read()['head']!=expected_head:raise ValueError('parent_head')
    # Validate a complete batch without writing anything to the supplied parent.
    journal.append_batch(envelope['events'],expected_head)
    snapshot=journal.read()
    if snapshot['state']['mode']!=envelope['data_kind']:raise ValueError('mixed_data_kind')
    diagnostic=learning_report(journal,evaluate_at)
    challenger=calibration_challenger(journal,train_cutoff,evaluate_at)
    backup=journal.backup(output/'model_snapshot.sqlite')
    (output/'state.json').write_text(encode(snapshot),encoding='utf-8')
    (output/'learning.json').write_text(encode(diagnostic),encoding='utf-8')
    (output/'challenger.json').write_text(encode(challenger),encoding='utf-8')
    manifest={'schema':'subscription-model-cycle-v1','data_kind':envelope['data_kind'],
        'events_sha256':events_hash,'parent_sha256':parent_hash,'expected_parent_head':expected_head,
        'journal_head':snapshot['head'],'backup':backup,'files':{},'orders_allowed':False,
        'commercial_release_allowed':False,'auto_promotion':False,'drive_restored':False}
    for f in sorted(output.iterdir()):
        if f.is_file():manifest['files'][f.name]=hashlib.sha256(f.read_bytes()).hexdigest()
    (output/'manifest.json').write_text(encode(manifest),encoding='utf-8')
    return manifest


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--events',type=Path,required=True);p.add_argument('--events-sha256',required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--expected-head',required=True)
    p.add_argument('--evaluate-at',required=True);p.add_argument('--train-cutoff',required=True)
    p.add_argument('--parent-db',type=Path);p.add_argument('--parent-sha256')
    a=p.parse_args();result=run(a.events,a.events_sha256,a.output,a.expected_head,a.evaluate_at,a.train_cutoff,a.parent_db,a.parent_sha256)
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
