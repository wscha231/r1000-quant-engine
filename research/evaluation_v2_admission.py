"""Native opt-in common-byte precheck. Not a trading engine or production gate.

Integrated with the existing run_ab_result_verifier; derived from prepared v1.
This module verifies supplied bytes and common environment identity ONLY.
It cannot authenticate a data provider, PIT correctness, a calendar, or approvals.
There are no file/network writes, no metrics, no rankings, and no book authority.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from datetime import date
from pathlib import Path
from typing import Callable, Any

SCHEMA = 'r1000-evaluation-v2-comparison-precheck-v2'
MAX_BLOB_BYTES = 1_048_576
MAX_TOTAL_BYTES = 16_777_216
MAX_NODES = 50_000
MAX_DEPTH = 32
CONTEXT_KEYS = frozenset({
    'schema', 'window_start', 'window_end', 'base_currency', 'initial_capital',
    'official_metric_mode', 'data_scope', 'shared_refs',
})
# Strategy outputs/feature sets deliberately do not belong in this common set.
SHARED_ROLES = frozenset({
    'data_release', 'eligible_universe', 'calendar', 'corporate_actions',
    'fx', 'benchmark', 'risk_free', 'execution_contract', 'cost_contract',
    'cash_accounting', 'metric_contract', 'evaluator_source', 'mission_contract',
    'pit_availability', 'reference_initial_capital', 'decision_clock_schema',
})
REF_KEYS = frozenset({'artifact_id', 'sha256'})
ARM_KEYS = frozenset({'schema', 'role', 'context_ref', 'strategy_ref'})
HEX64 = re.compile(r'[0-9a-f]{64}')
ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,199}')
DEVICE_IDS = frozenset({'CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$'} |
                       {f'{prefix}{i}' for prefix in ('COM', 'LPT') for i in range(1, 10)})
UNVERIFIED = (
    'PROVIDER_AUTHENTICITY_AND_PUBLIC_AVAILABILITY',
    'PIT_UNIVERSE_AND_DATA_COMPLETENESS',
    'EXECUTED_CODE_VS_DECLARED_CODE',
    'EXECUTION_COST_CASH_CORPORATE_ACTION_RECONCILIATION',
    'OOS_EXPOSURE_AND_INDEPENDENT_REVIEW',
)

class AdmissionError(ValueError):
    """Bounded reason code; never includes provider exception text."""

def require(ok: bool, reason: str) -> None:
    if not ok:
        raise AdmissionError(reason)

def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()

def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('utf-8')

def _keys(value: Any, keys: frozenset[str], reason: str) -> None:
    require(type(value) is dict and set(value) == keys, reason)

def _pairs(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        require(key not in result, 'DUPLICATE_JSON_KEY')
        result[key] = value
    return result

def _constant(_value: str) -> None:
    raise AdmissionError('NONFINITE_JSON')

def strict_json(raw: bytes) -> dict:
    require(type(raw) is bytes and len(raw) <= MAX_BLOB_BYTES, 'JSON_TYPE_OR_SIZE')
    try:
        text = raw.decode('utf-8')
        depth = 0; quoted = False; escaped = False
        for char in text:
            if quoted:
                if escaped: escaped = False
                elif char == '\\': escaped = True
                elif char == '"': quoted = False
            elif char == '"': quoted = True
            elif char in '[{':
                depth += 1
                require(depth <= MAX_DEPTH, 'JSON_DEPTH')
            elif char in ']}': depth -= 1
        value = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
    except AdmissionError:
        raise
    except (UnicodeError, ValueError, RecursionError):
        raise AdmissionError('INVALID_JSON') from None
    require(type(value) is dict, 'JSON_OBJECT_REQUIRED')
    pending = [value]; nodes = 0
    while pending:
        item = pending.pop(); nodes += 1
        require(nodes <= MAX_NODES, 'JSON_NODE_BUDGET')
        if type(item) is float:
            require(math.isfinite(item), 'NONFINITE_JSON')
        elif type(item) is dict:
            pending.extend(item.values())
        elif type(item) is list:
            pending.extend(item)
    return value

def validate_ref(value: Any) -> dict:
    _keys(value, REF_KEYS, 'REFERENCE_FIELDS')
    validate_artifact_id(value['artifact_id'])
    require(type(value['sha256']) is str and HEX64.fullmatch(value['sha256']) is not None,
            'ARTIFACT_HASH')
    return value

def validate_artifact_id(value: Any) -> None:
    """Flat opaque IDs, never arbitrary paths or Windows device/stream aliases."""
    require(type(value) is str and ID.fullmatch(value) is not None
            and not value.endswith('.') and value.split('.')[0].upper() not in DEVICE_IDS,
            'ARTIFACT_ID')

def _file_identity(value: os.stat_result) -> tuple:
    # Windows ctime is deprecated and may differ between stat/fstat APIs.
    # Use explicit creation time there; content mtime and file ID remain bound.
    generation_time = getattr(value, 'st_birthtime_ns', value.st_ctime_ns) if os.name == 'nt' else value.st_ctime_ns
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size,
            value.st_mtime_ns, generation_time)

def _is_link(value: os.stat_result) -> bool:
    return stat.S_ISLNK(value.st_mode) or bool(
        getattr(value, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)
    )

class BoundedArtifactResolver:
    """Read a caller-selected immutable flat bundle with bounded, redacted IO.

    This is a byte snapshot boundary, not provider authentication or an OS sandbox.
    Root/leaf aliases and descriptor changes fail closed before bytes are returned.
    """
    def __init__(self, root: str | Path):
        require(type(root) is str or isinstance(root, Path), 'ARTIFACT_ROOT_INVALID')
        require(bool(str(root)), 'ARTIFACT_ROOT_INVALID')
        try:
            self.root = Path(root).absolute()
            self._check_root_path()
            observed = self.root.stat()
            require(observed.st_ino != 0, 'ARTIFACT_ROOT_INVALID')
            self.root_identity = (observed.st_dev, observed.st_ino)
        except AdmissionError:
            raise
        except (OSError, ValueError, RuntimeError):
            raise AdmissionError('ARTIFACT_ROOT_INVALID') from None
        self.returned_bytes = 0
        self.cache: dict[str, bytes] = {}
        self.identities: dict[str, tuple] = {}

    def _check_root_path(self) -> None:
        # Reject symbolic links/junctions in every component, including the root.
        for component in (self.root, *self.root.parents):
            require(not _is_link(component.lstat()), 'ARTIFACT_ROOT_INVALID')
        require(self.root.is_dir() and self.root.resolve(strict=True) == self.root,
                'ARTIFACT_ROOT_INVALID')

    def _guard_root(self) -> None:
        self._check_root_path()
        observed = self.root.stat()
        require((observed.st_dev, observed.st_ino) == self.root_identity, 'ARTIFACT_ROOT_CHANGED')

    def validate_cached(self, artifact_id: str) -> None:
        """Revalidate physical snapshot identity without rereading or recharging."""
        try:
            self._guard_root()
            path = self.root / artifact_id
            observed = path.lstat()
            require(not _is_link(observed) and stat.S_ISREG(observed.st_mode), 'ARTIFACT_FILE_TYPE')
            require(_file_identity(observed) == self.identities[artifact_id], 'ARTIFACT_CHANGED')
            require(path.resolve(strict=True).parent == self.root, 'ARTIFACT_PATH')
        except AdmissionError:
            raise
        except (OSError, ValueError, RuntimeError, KeyError):
            raise AdmissionError('ARTIFACT_UNAVAILABLE') from None

    def validate_snapshot(self) -> None:
        # The final comparison may consist entirely of _Snapshot cache hits.
        # Bind the root and every returned leaf after the last comparison read.
        try:
            self._guard_root()
            for artifact_id in self.cache:
                self.validate_cached(artifact_id)
            self._guard_root()
        except AdmissionError:
            raise
        except (OSError, ValueError, RuntimeError):
            raise AdmissionError('ARTIFACT_UNAVAILABLE') from None

    def __call__(self, artifact_id: str) -> bytes:
        validate_artifact_id(artifact_id)
        if artifact_id in self.cache:
            self.validate_cached(artifact_id)
            return self.cache[artifact_id]
        fd = None
        try:
            self._guard_root()
            path = self.root / artifact_id
            before = path.lstat()
            require(not _is_link(before) and stat.S_ISREG(before.st_mode) and before.st_ino != 0,
                    'ARTIFACT_FILE_TYPE')
            require(path.resolve(strict=True).parent == self.root, 'ARTIFACT_PATH')
            require(before.st_size <= MAX_BLOB_BYTES, 'ARTIFACT_BYTE_BUDGET')
            require(self.returned_bytes + before.st_size <= MAX_TOTAL_BYTES, 'TOTAL_BYTE_BUDGET')
            # Nonblocking open prevents a raced regular-to-FIFO replacement
            # from hanging before its descriptor type can be rejected.
            flags = (os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
                     | getattr(os, 'O_NONBLOCK', 0))
            fd = os.open(path, flags)
            require(_file_identity(os.fstat(fd)) == _file_identity(before), 'ARTIFACT_CHANGED')
            self._guard_root()
            require(_file_identity(path.lstat()) == _file_identity(before), 'ARTIFACT_CHANGED')
            chunks = []
            # Never probe a sentinel byte beyond either allowance. The known
            # size is also a read cap; final descriptor/leaf checks detect a
            # concurrent extension even when no extra byte is consumed.
            remaining = min(before.st_size, MAX_BLOB_BYTES,
                            MAX_TOTAL_BYTES - self.returned_bytes)
            while remaining:
                part = os.read(fd, min(65536, remaining))
                if not part:
                    break
                chunks.append(part)
                remaining -= len(part)
                # A later read error must not erase bytes already consumed.
                self.returned_bytes += len(part)
            raw = b''.join(chunks)
            require(len(raw) <= MAX_BLOB_BYTES, 'ARTIFACT_BYTE_BUDGET')
            require(self.returned_bytes <= MAX_TOTAL_BYTES, 'TOTAL_BYTE_BUDGET')
            require(len(raw) == before.st_size and _file_identity(os.fstat(fd)) == _file_identity(before),
                    'ARTIFACT_CHANGED')
            self._guard_root()
            require(_file_identity(path.lstat()) == _file_identity(before), 'ARTIFACT_CHANGED')
            self.cache[artifact_id] = raw
            self.identities[artifact_id] = _file_identity(before)
            return raw
        except AdmissionError:
            raise
        except (OSError, ValueError, RuntimeError):
            raise AdmissionError('ARTIFACT_UNAVAILABLE') from None
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    raise AdmissionError('ARTIFACT_UNAVAILABLE') from None

class _Snapshot:
    """The supplied resolver is a trusted read boundary, not an OS sandbox."""
    def __init__(self, resolver: Callable[[str], bytes]):
        self.resolver = resolver
        self.bindings: dict[str, str] = {}
        self.cache: dict[str, bytes] = {}
        self.returned_bytes = 0

    def read(self, ref: dict) -> bytes:
        validate_ref(ref)
        key, expected = ref['artifact_id'], ref['sha256']
        require(key not in self.bindings or self.bindings[key] == expected,
                'ARTIFACT_ID_CONFLICT')
        self.bindings[key] = expected
        if key in self.cache:
            if type(self.resolver) is BoundedArtifactResolver:
                self.resolver.validate_cached(key)
            return self.cache[key]
        try:
            raw = self.resolver(key)
        except AdmissionError:
            # Only the internally constructed native resolver emits our bounded
            # reason codes. Foreign provider exception text stays redacted.
            if type(self.resolver) is BoundedArtifactResolver:
                raise
            raise AdmissionError('ARTIFACT_UNAVAILABLE') from None
        except Exception:
            raise AdmissionError('ARTIFACT_UNAVAILABLE') from None
        require(type(raw) is bytes, 'ARTIFACT_TYPE')
        # Charge failures, too; size checks do not mean the bytes were verified.
        self.returned_bytes += len(raw)
        require(self.returned_bytes <= MAX_TOTAL_BYTES, 'TOTAL_BYTE_BUDGET')
        require(len(raw) <= MAX_BLOB_BYTES, 'ARTIFACT_BYTE_BUDGET')
        require(digest(raw) == expected, 'ARTIFACT_HASH_MISMATCH')
        self.cache[key] = raw
        return raw

def _day(value: Any) -> date:
    require(type(value) is str and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value) is not None,
            'WINDOW_DATE')
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise AdmissionError('WINDOW_DATE') from None

def _context(value: dict) -> None:
    _keys(value, CONTEXT_KEYS, 'CONTEXT_FIELDS')
    require(value['schema'] == SCHEMA, 'SCHEMA')
    require(_day(value['window_start']) < _day(value['window_end']), 'WINDOW_ORDER')
    require(type(value['base_currency']) is str and re.fullmatch(r'[A-Z]{3}', value['base_currency']) is not None,
            'CURRENCY')
    cap = value['initial_capital']
    require(type(cap) in (int, float) and 0 < cap <= 1e15 and math.isfinite(cap),
            'INITIAL_CAPITAL')
    require(value['official_metric_mode'] == 'broker_ledger_next_close', 'OFFICIAL_MODE_UNCHANGED')
    require(type(value['data_scope']) is str and value['data_scope'] in ('SYNTHETIC', 'HISTORICAL_RESEARCH', 'FORWARD_RESEARCH'), 'DATA_SCOPE')
    _keys(value['shared_refs'], SHARED_ROLES, 'SHARED_ROLES')
    for ref in value['shared_refs'].values():
        validate_ref(ref)

def compare_environment(control: dict, challenger: dict, *, expected_context_sha256: str,
                        artifact_resolver: Callable[[str], bytes]) -> dict:
    """Expected hash must come from a separately pinned caller contract.

    Even a matching hash proves byte identity only; returns NO investment authority.
    """
    require(type(expected_context_sha256) is str and HEX64.fullmatch(expected_context_sha256) is not None,
            'EXPECTED_CONTEXT_HASH_REQUIRED')
    snapshot = _Snapshot(artifact_resolver)
    arms = []
    for arm, role in ((control, 'CONTROL'), (challenger, 'CHALLENGER')):
        _keys(arm, ARM_KEYS, 'ARM_FIELDS')
        require(arm['schema'] == SCHEMA and arm['role'] == role, 'ARM_ROLE_OR_SCHEMA')
        validate_ref(arm['context_ref']); validate_ref(arm['strategy_ref'])
        require(arm['context_ref']['sha256'] == expected_context_sha256, 'CONTEXT_PIN_MISMATCH')
        context_raw = snapshot.read(arm['context_ref'])
        value = strict_json(context_raw); _context(value)
        for name in sorted(SHARED_ROLES):
            snapshot.read(value['shared_refs'][name])
        snapshot.read(arm['strategy_ref'])
        arms.append((context_raw, value))
    require(arms[0][0] == arms[1][0], 'CONTEXT_BYTES_MISMATCH')
    resolved_artifacts, resolved_bytes = len(snapshot.cache), snapshot.returned_bytes
    if type(artifact_resolver) is BoundedArtifactResolver:
        artifact_resolver.validate_snapshot()
        # Include declarations preloaded by the native caller. Each flat ID is
        # charged once by the same resolver that enforces the aggregate budget.
        resolved_artifacts = len(artifact_resolver.cache)
        resolved_bytes = artifact_resolver.returned_bytes
    return {
        'schema': SCHEMA, 'status': 'BYTE_COMPARABLE_RESEARCH_ONLY',
        'context_sha256': expected_context_sha256,
        'shared_roles_verified': sorted(SHARED_ROLES),
        'data_scope': arms[0][1]['data_scope'],
        'resolved_artifacts': resolved_artifacts, 'resolved_bytes': resolved_bytes,
        'strategy_refs': {'control': dict(control['strategy_ref']), 'challenger': dict(challenger['strategy_ref'])},
        'unverified_domains': list(UNVERIFIED), 'g0_certified': False,
        'economic_comparison_ready': False, 'champion_promotion_allowed': False,
        'public_publication_allowed': False, 'fullrun_allowed': False,
        'target_paper_broker_mutation_allowed': False,
    }
