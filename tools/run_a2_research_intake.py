"""Read already-held event evidence into the existing A2 proposal API.

No fetcher, scheduler, Registry writer or source/economic admission is provided.
The caller owns the read-only input tree and supplies an exact request hash and
cutoff. A new result file is an execution output, never a current-state pointer.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from research import a2_research_intake_v1 as intake


def need(ok, reason):
    if not ok:
        raise intake.IntakeError(reason)


class Files:
    """Bound reads before allocation; never resolve URLs or traversal aliases.

    This is a loader for a caller-owned, stable local tree, not an OS sandbox
    against a concurrent hostile filesystem writer.
    """
    def __init__(self, root):
        root = Path(root)
        need(not root.is_symlink() and root.is_dir(), 'INPUT_ROOT')
        self.root = root.resolve()
        self.total = 0
        self.read_set = []

    def read(self, ref, role, artifact_id=None):
        need(type(ref) is dict and set(ref) == {'path', 'sha256'}, 'FILE_REFERENCE')
        name, sha = ref['path'], ref['sha256']
        need(type(name) is str and 0 < len(name) <= 512
             and not any(c in name for c in '\\:*?[]\x00'), 'FILE_PATH')
        parts = name.split('/')
        need(not PurePosixPath(name).is_absolute()
             and all(p not in ('', '.', '..') for p in parts), 'FILE_PATH')
        need(type(sha) is str and len(sha) == 64
             and all(c in '0123456789abcdef' for c in sha), 'FILE_HASH')
        path = self.root
        for part in parts:
            path = path / part
            info = path.lstat()
            need(not stat.S_ISLNK(info.st_mode)
                 and not (getattr(info, 'st_file_attributes', 0) & 0x400), 'FILE_LINK')
        need(stat.S_ISREG(info.st_mode), 'FILE_REGULAR')
        need(path.resolve().is_relative_to(self.root), 'FILE_PATH')
        with path.open('rb') as stream:
            info = os.fstat(stream.fileno())
            need(stat.S_ISREG(info.st_mode), 'FILE_REGULAR')
            need(0 < info.st_size <= intake.MAX_BYTES, 'FILE_BYTE_BUDGET')
            need(self.total + info.st_size <= intake.MAX_TOTAL_BYTES, 'FILE_TOTAL_BUDGET')
            raw = stream.read(min(intake.MAX_BYTES,
                                  intake.MAX_TOTAL_BYTES - self.total) + 1)
        need(len(raw) == info.st_size and len(raw) <= intake.MAX_BYTES,
             'FILE_CHANGED_OR_BYTE_BUDGET')
        self.total += len(raw)
        need(intake.digest(raw) == sha, 'FILE_HASH_MISMATCH')
        self.read_set.append(dict(role=role, artifact_id=artifact_id, path=name,
                                  sha256=sha, bytes=len(raw)))
        return raw


def prepare(*, input_root, request_path, request_sha256, cutoff):
    intake.stamp(cutoff)
    files = Files(input_root)
    request_raw = files.read({'path': request_path, 'sha256': request_sha256}, 'request')
    request = intake.decode(request_raw)
    need(set(request) == {'schema', 'events', 'identities', 'artifacts', 'event_sources'}
         and request['schema'] == 'a2-file-intake-v1', 'FILE_REQUEST_FIELDS')
    rows = request['artifacts']
    need(type(rows) is list and len(rows) <= intake.MAX_ARTIFACTS, 'FILE_ARTIFACT_COUNT')
    memory, hashes = {}, {}
    for row in rows:
        need(type(row) is dict and set(row) == {'artifact_id', 'path', 'sha256'},
             'FILE_ARTIFACT_FIELDS')
        aid = intake.identifier(row['artifact_id'])
        need(aid not in memory and not aid.startswith('SCHEMA:'), 'FILE_ARTIFACT_ID')
        raw = files.read({'path': row['path'], 'sha256': row['sha256']}, 'artifact', aid)
        memory[aid], hashes[aid] = raw, row['sha256']
    events_raw = files.read(request['events'], 'events')
    identities_raw = files.read(request['identities'], 'identities')
    schema_name, schema_sha = intake.SCHEMAS['events']
    schema_raw = Files(ROOT).read({'path': 'research/control_plane/' + schema_name,
                                   'sha256': schema_sha}, 'schema')
    memory['SCHEMA:' + schema_name] = schema_raw
    result = intake.validate_events(events_raw, cutoff=cutoff,
        artifact_resolver=intake.MemoryArtifacts(memory), identities=identities_raw)
    bindings = request['event_sources']
    need(type(bindings) is dict
         and set(bindings) == {row['event_id'] for row in result['events']},
         'FILE_EVENT_SOURCE_SCOPE')
    sources = {}
    for eid, aids in bindings.items():
        need(type(aids) is list and 0 < len(aids) <= 10
             and all(type(aid) is str and aid in hashes for aid in aids)
             and len(aids) == len(set(aids)), 'FILE_EVENT_SOURCE_REFERENCE')
        sources[eid] = [dict(artifact_id=aid, sha256=hashes[aid]) for aid in aids]
    return dict(schema='a2-file-intake-result-v1', status='READ_ONLY_RESEARCH_PROPOSAL',
        cutoff=cutoff, request_sha256=intake.digest(request_raw),
        code_identity=dict(adapter_sha256=intake.digest(Path(__file__).read_bytes()),
                           intake_sha256=intake.digest(Path(intake.__file__).read_bytes()),
                           schema_sha256=schema_sha),
        read_set=files.read_set, event_source_bindings=sources, proposal=result,
        source_authenticity='NOT_VERIFIED', semantic_claim_review='NOT_VERIFIED',
        recurring_pipeline_connected=False, authority=intake.closed())


def write_result(path, result):
    """Expose the final name only after the local file has fully closed.

    Hard-link creation is atomic/create-only on the supported local filesystem.
    Unsupported filesystems fail closed. This is not a durable account commit.
    """
    raw = intake.canonical(result)
    path, temporary, cleanup = Path(path), None, True
    try:
        with tempfile.NamedTemporaryFile(mode='wb', dir=path.parent,
                prefix='.a2-intake-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            need(stream.write(raw) == len(raw), 'OUTPUT_SHORT_WRITE')
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                # A cleanup failure cannot undo a published, complete result
                # or change a pre-publication refusal into a successful result.
                cleanup = False
    return dict(status=result['status'], result_sha256=intake.digest(raw),
                bytes=len(raw), temporary_cleanup_complete=cleanup)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-root', required=True)
    parser.add_argument('--request', required=True, help='Relative path below the read-only input root')
    parser.add_argument('--request-sha256', required=True)
    parser.add_argument('--cutoff', required=True, help='Explicit aware research cutoff; no wallclock inference')
    parser.add_argument('--output', required=True, help='A new local proposal file; parent must already exist')
    args = parser.parse_args(argv)
    try:
        need(not Path(args.output).exists() and not Path(args.output).is_symlink(),
             'OUTPUT_ALREADY_EXISTS')
        result = prepare(input_root=args.input_root, request_path=args.request,
                         request_sha256=args.request_sha256, cutoff=args.cutoff)
        summary = write_result(args.output, result)
    except intake.IntakeError as exc:
        summary = dict(status='BLOCKED', reason=str(exc), result_completed=False)
    except OSError:
        summary = dict(status='BLOCKED', reason='FILE_ACCESS_OR_EXISTING_OUTPUT', result_completed=False)
    print(json.dumps(summary, sort_keys=True))
    return 2 if summary['status'] == 'BLOCKED' else 0


if __name__ == '__main__':
    raise SystemExit(main())
