"""Collect only the missing long-RS window and reconcile its overlap.

This extends current-security discovery histories, not historical membership.
Original raw/adjusted source responses stay in a separate private snapshot.
"""
from datetime import date,timedelta
import json
import math
import os
from pathlib import Path
import re
import subprocess

from research_source_connection import Capture,collect_bars,canonical,digest_bytes,guarded,now,save_private


def merge_histories(current,older,first_current):
    merged={basis:{t:list(rows) for t,rows in symbols.items()} for basis,symbols in current.items()}
    statuses={}
    for ticker in current['all']:
        a={r['t'][:10]:r for r in current['all'][ticker]}
        b={r['t'][:10]:r for r in older['all'].get(ticker,[])}
        overlap=sorted(set(a)&set(b))
        raw_a={r['t'][:10]:r for r in current['raw'].get(ticker,[])}
        raw_b={r['t'][:10]:r for r in older['raw'].get(ticker,[])}
        if len(overlap)<5:
            statuses[ticker]='insufficient_overlap_or_short_listing';continue
        ratios=[a[d]['c']/b[d]['c'] for d in overlap]
        ratio=ratios[0]
        if (any(not math.isclose(r,ratio,rel_tol=1e-7) for r in ratios) or
                any(d not in raw_a or d not in raw_b or not math.isclose(raw_a[d]['c'],raw_b[d]['c'],rel_tol=1e-8)
                    for d in overlap)):
            statuses[ticker]='source_overlap_conflict';continue
        for basis in ('raw','all'):
            prefix=[dict(r,c=r['c']*(ratio if basis=='all' else 1.))
                for r in older[basis].get(ticker,[]) if r['t'][:10]<first_current]
            # Only the close is consumed for these derived discovery series;
            # source OHLC/volume rows remain immutable in the private capture.
            merged[basis][ticker]=prefix+current[basis].get(ticker,[])
        statuses[ticker]='extended' if any(d<first_current for d in b) else 'no_earlier_history'
    return merged,statuses


def extend(current,report,root):
    root=Path(root);capture=Capture(root)
    stop=(date.fromisoformat(report['start'])+timedelta(days=45)).isoformat()
    symbols=sorted(current['all'])
    collected=guarded('US_RS_HISTORY_EXTENSION',lambda:collect_bars(capture,'2024-05-01',stop,symbols))
    summary=dict(schema_version='research-source-connection-v1',data_kind='REAL',generated_at=now(),
        start='2024-05-01',end=stop,extension_only=True,base_receipts_hash=report['source_receipts_hash'],
        source_receipt_count=len(capture.receipts),source_receipts_hash=digest_bytes(canonical(capture.receipts)),
        status=collected['status'],candidate_count=len(symbols),historical_membership_verified=False)
    save_private(root/'receipts.json',canonical(capture.receipts))
    save_private(root/'connection_report.json',canonical(summary))
    if collected['status']!='COLLECTED':
        summary['reason']=collected.get('reason');return current,summary
    older=json.loads((root/'bars.json').read_text())
    merged,statuses=merge_histories(current,older,report['start'])
    from collections import Counter
    summary['merge_counts']=dict(Counter(statuses.values()))
    save_private(root/'merge_statuses.json',canonical(statuses))
    return merged,summary


def persist(root):
    runner=Path(os.environ['RUNNER_TEMP'])
    binary=runner/'us-research-reuse/rclone'
    config=runner/'us-rs-extension-rclone.conf'
    snapshot=os.environ['GITHUB_RUN_ID']+'-'+os.environ['GITHUB_RUN_ATTEMPT']+'-'+os.environ['RESEARCH_SOURCE_COMMIT']
    if not re.fullmatch(r'[0-9]+-[0-9]+-[0-9a-f]{40}',snapshot):raise ValueError('extension_snapshot_identity')
    phase='setup'
    try:
        with config.open('x') as f:f.write(os.environ['RESEARCH_RCLONE_CONFIG'])
        config.chmod(0o600)
        remote='gdrive:research_source_extensions/'+snapshot+'/'
        common=[str(binary),'--config',str(config)]
        phase='copy'
        subprocess.run(common+['copy',str(root),remote,'--immutable','--transfers','4','--checkers','4'],
            check=True,timeout=600,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        phase='byte_check'
        subprocess.run(common+['check',str(root),remote,'--download','--one-way','--checkers','4'],
            check=True,timeout=300,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        return dict(status='VERIFIED_PRIVATE_EXTENSION',snapshot=snapshot)
    except Exception:
        return dict(status='BLOCKED',reason=phase+'_not_verified')
    finally:config.unlink(missing_ok=True)
