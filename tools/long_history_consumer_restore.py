#!/usr/bin/env python3
"""Read a named Drive export through Lake's full validators, without a producer.

The input is a content-addressed local export acquired separately from Drive.
This verifies storage and a bounded SQL slice, not completed study/execution,
historical PIT, source admission, or an investment decision. No remote transport
constructor, provider, scheduler or receipt writer is invoked.
"""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.long_history_lake import Lake, PREFIX, materialize
from tools.macro_history_sources import digest, encoded, exclusive, require, utc_now
from tools.macro_research_checkpoint import MAX_OBJECT, relative, safe_path

MAX_READ_BYTES=1024*1024*1024


class SnapshotReadOnlyTransport:
    """Existing files only; local verification is never remote publication proof."""
    remote_verified=False

    def __init__(self,root):
        self.root=safe_path(root)
        require(self.root.is_dir(),'snapshot_missing')
        self.read_calls=0
        self.read_bytes=0

    def names(self,prefix):
        path=safe_path(self.root/relative(prefix))
        if not path.exists(): return []
        require(path.is_dir(),'snapshot_directory')
        return sorted(p.name for p in path.iterdir() if p.is_file())

    def read(self,path):
        target=safe_path(self.root/relative(path))
        fd=os.open(target,os.O_RDONLY|getattr(os,'O_NONBLOCK',0)|getattr(os,'O_NOFOLLOW',0))
        with os.fdopen(fd,'rb') as handle:
            info=os.fstat(handle.fileno())
            require(stat.S_ISREG(info.st_mode),'snapshot_regular_file')
            size=info.st_size
            require(0<size<=MAX_OBJECT,'snapshot_object_size')
            require(self.read_calls<10000 and self.read_bytes+size<=MAX_READ_BYTES,
                    'snapshot_read_budget')
            raw=handle.read(min(MAX_OBJECT,MAX_READ_BYTES-self.read_bytes)+1)
        require(len(raw)==size,'snapshot_object_changed')
        self.read_calls+=1
        self.read_bytes+=len(raw)
        return raw

    def write(self,*_):
        raise ValueError('read_only_snapshot')


class _PinnedReadOnly:
    def __init__(self,transport,commit_sha256):
        self.transport=transport
        self.remote_verified=False
        self.commits=[]
        current=commit_sha256
        while current is not None:
            require(isinstance(current,str) and re.fullmatch('[a-f0-9]{64}',current),
                    'hash_identity')
            require(current not in self.commits and len(self.commits)<20000,'pinned_chain')
            raw=self.read(f'{PREFIX}/commits/{current}')
            require(digest(raw)==current,'remote_hash')
            commit=json.loads(raw)
            require(isinstance(commit,dict) and 'parent' in commit,'pinned_chain')
            self.commits.append(current)
            current=commit['parent']

    def read(self,path):
        return self.transport.read(path)

    def names(self,prefix):
        require(prefix==f'{PREFIX}/commits','consumer_read_scope')
        return sorted(self.commits)

    def write(self,*_):
        raise ValueError('read_only_snapshot')


def restore_consumer(transport,output,*,commit_sha256,catalog_sha256,datasets,cutoff):
    require(isinstance(catalog_sha256,str) and re.fullmatch('[a-f0-9]{64}',catalog_sha256),
            'hash_identity')
    require(isinstance(datasets,(list,tuple)) and 0<len(datasets)<=16 and
            len(set(datasets))==len(datasets),'consumer_datasets')
    require(date.fromisoformat(cutoff)<=date.today(),'future_cutoff')
    output=safe_path(output)
    require(not output.exists(),'consumer_output_exists')
    pinned=_PinnedReadOnly(transport,commit_sha256)
    # Default restore performs every ancestral catalog/pack/member check.
    lake=Lake(pinned,output/'cache')
    commit=json.loads(lake.read_hash('commits',lake.parent))
    require(lake.parent==commit_sha256 and commit['catalog']==catalog_sha256,
            'consumer_pin_mismatch')
    require(all(key in lake.catalog['datasets'] for key in datasets),'consumer_dataset_missing')
    rows=materialize(lake,output/'slice.sqlite',datasets,cutoff)
    with (output/'slice.sqlite').open('rb') as database:
        database_hash=hashlib.file_digest(database,'sha256').hexdigest()
    result=dict(schema='long-history-consumer-readback-v1',created_at=utc_now(),
        status='STORAGE_AND_SQL_VERIFIED',commit_sha256=commit_sha256,
        catalog_sha256=catalog_sha256,generation=lake.catalog['generation'],
        ancestral_commits=len(pinned.commits),datasets=list(datasets),cutoff=cutoff,
        consumer_rows=rows,quality_status='NOT_EVALUATED',study_status='NOT_RUN',
        verified_execution=False,source_admitted=False,historical_pit_certified=False,
        eligible_for_selector=False,eligible_for_economics=False,
        provider_calls=0,remote_writes=0,
        input_transport='READ_ONLY_LOCAL_DRIVE_EXPORT',remote_verified=False,
        database_sha256=database_hash)
    exclusive(output/'readback.json',encoded(result))
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--snapshot',required=True)
    p.add_argument('--output',required=True)
    p.add_argument('--commit-sha256',required=True)
    p.add_argument('--catalog-sha256',required=True)
    p.add_argument('--dataset',action='append',required=True)
    p.add_argument('--cutoff',required=True)
    args=p.parse_args()
    transport=SnapshotReadOnlyTransport(args.snapshot)
    result=restore_consumer(transport,args.output,commit_sha256=args.commit_sha256,
        catalog_sha256=args.catalog_sha256,datasets=args.dataset,cutoff=args.cutoff)
    print(json.dumps(dict(result,read_calls=transport.read_calls,read_bytes=transport.read_bytes)))
    return 0


if __name__=='__main__':
    try: raise SystemExit(main())
    except (ValueError,KeyError,TypeError,OSError):
        raise SystemExit('LONG_HISTORY_CONSUMER_BLOCKED') from None
