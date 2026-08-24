"""Append-only receipts and content-addressed artifacts for Peer Wake v0.3."""
from __future__ import annotations
import hashlib
import hmac
import json
import os
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, Mapping, Optional, Tuple
try:
    import fcntl
except ImportError:  # supported sentinel host is POSIX/Linux
    fcntl = None
from peer_wake_models import WakeDecision, WakeEnvelope, canonical_json, receipt_hash, sha256_json

class ReceiptLog:
    """Append-only, hash-chained records with an exclusive commit lock."""

    def __init__(self, path: os.PathLike[str] | str):
        self.path = Path(path)
        self.lock_path = Path(str(self.path) + '.lock')

    def records(self) -> Iterable[Dict[str, Any]]:
        if not self.path.exists():
            return []
        records = []
        with self.path.open('r', encoding='utf-8') as handle:
            for line_no, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f'receipt log malformed at line {line_no}: {exc}') from exc
                if not isinstance(record, dict):
                    raise ValueError(f'receipt log line {line_no} is not an object')
                records.append(record)
        return records

    @contextmanager
    def exclusive_lock(self) -> Iterator[None]:
        if fcntl is None:
            raise OSError('peer wake receipt locking requires POSIX fcntl')
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open('a+', encoding='utf-8') as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

    def verify_chain(self) -> Tuple[bool, str]:
        previous = ''
        for index, record in enumerate(self.records(), 1):
            if record.get('prev_hash', '') != previous:
                return (False, f'line {index}: prev_hash mismatch')
            expected = receipt_hash(record)
            if record.get('receipt_hash') != expected:
                return (False, f'line {index}: receipt_hash mismatch')
            previous = str(record['receipt_hash'])
        return (True, previous)

    def _append_unlocked(self, record: Mapping[str, Any]) -> Dict[str, Any]:
        ok, head = self.verify_chain()
        if not ok:
            raise ValueError(f'refusing to append to invalid receipt chain: {head}')
        committed = dict(record)
        committed['prev_hash'] = head
        committed['receipt_hash'] = receipt_hash(committed)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open('a', encoding='utf-8') as handle:
            handle.write(canonical_json(committed) + '\n')
            handle.flush()
            os.fsync(handle.fileno())
        return committed

    def append(self, record: Mapping[str, Any]) -> Dict[str, Any]:
        with self.exclusive_lock():
            return self._append_unlocked(record)

    def consumed(self, envelope: WakeEnvelope) -> bool:
        for record in self.records():
            if record.get('record_type') != 'peer_request':
                continue
            if record.get('envelope_id') == envelope.envelope_id:
                return True
            if record.get('sender') == envelope.sender and record.get('nonce') == envelope.nonce:
                return True
        return False

    def find_queued(self, envelope_hash: str) -> Optional[Dict[str, Any]]:
        for record in reversed(list(self.records())):
            if record.get('record_type') == 'peer_request' and record.get('envelope_hash') == envelope_hash and (record.get('decision') == WakeDecision.REQUEST_QUEUED.value):
                return record
        return None

    def already_authorized(self, envelope_hash: str) -> bool:
        return any((record.get('record_type') == 'local_authorization_decision' and record.get('envelope_hash') == envelope_hash and (record.get('decision') == WakeDecision.WAKE_AUTHORIZED.value) for record in self.records()))

class JsonArtifactStore:
    """Canonical JSON artifact store addressed by content hash."""

    def __init__(self, root: os.PathLike[str] | str):
        self.root = Path(root)

    def store(self, value: Mapping[str, Any]) -> str:
        content = canonical_json(value)
        digest = hashlib.sha256(content.encode('utf-8')).hexdigest()
        ref = f'{digest}.json'
        path = self.root / ref
        self.root.mkdir(parents=True, exist_ok=True)
        if path.exists():
            existing = path.read_text(encoding='utf-8')
            if existing != content + '\n':
                raise ValueError(f'artifact hash collision or noncanonical file: {path}')
            return ref
        temp = self.root / f'.{digest}.{uuid.uuid4().hex}.tmp'
        try:
            with temp.open('x', encoding='utf-8') as handle:
                handle.write(content + '\n')
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
            _fsync_directory(self.root)
        finally:
            if temp.exists():
                temp.unlink()
        return ref

    def load(self, ref: str) -> Dict[str, Any]:
        if '/' in ref or '\\' in ref or (not ref.endswith('.json')):
            raise ValueError('invalid artifact reference')
        path = self.root / ref
        with path.open('r', encoding='utf-8') as handle:
            value = json.load(handle)
        if not isinstance(value, dict):
            raise ValueError(f'artifact {ref} is not an object')
        expected = ref.removesuffix('.json')
        actual = sha256_json(value)
        if not hmac.compare_digest(actual, expected):
            raise ValueError(f'artifact {ref} content hash mismatch')
        return value

def _fsync_directory(path: Path) -> None:
    flags = getattr(os, 'O_DIRECTORY', 0) | os.O_RDONLY
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
