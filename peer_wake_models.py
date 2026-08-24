"""Data contracts and deterministic validation for GLEE Peer Wake v0.3."""
from __future__ import annotations
import hashlib
import hmac
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

PROTOCOL = "glee.peer-wake/v0.3"
AUTHORIZATION_PROTOCOL = "glee.local-wake-authorization/v0.3"
SIGNATURE_ALG = "hmac-sha256"

class WakeDecision(str, Enum):
    REQUEST_QUEUED = 'REQUEST_QUEUED'
    DECLINED_LOCAL_POLICY = 'DECLINED_LOCAL_POLICY'
    DECLINED_UNAUTHORIZED = 'DECLINED_UNAUTHORIZED'
    DECLINED_BAD_SIGNATURE = 'DECLINED_BAD_SIGNATURE'
    DECLINED_EXPIRED = 'DECLINED_EXPIRED'
    DECLINED_FUTURE_ISSUE = 'DECLINED_FUTURE_ISSUE'
    DECLINED_WRONG_RECIPIENT = 'DECLINED_WRONG_RECIPIENT'
    DECLINED_REPLAY = 'DECLINED_REPLAY'
    DECLINED_REQUEST_NOT_QUEUED = 'DECLINED_REQUEST_NOT_QUEUED'
    DECLINED_SLEEP_POLICY = 'DECLINED_SLEEP_POLICY'
    DECLINED_MALFORMED = 'DECLINED_MALFORMED'
    HELD_QUEUE_ONLY = 'HELD_QUEUE_ONLY'
    HELD_OPERATOR_STOP = 'HELD_OPERATOR_STOP'
    HELD_MINIMUM_SLEEP = 'HELD_MINIMUM_SLEEP'
    HELD_NO_SLEEP_CONTRACT = 'HELD_NO_SLEEP_CONTRACT'
    WAKE_AUTHORIZED = 'WAKE_AUTHORIZED'

HELD_DECISIONS = {
    WakeDecision.HELD_QUEUE_ONLY,
    WakeDecision.HELD_OPERATOR_STOP,
    WakeDecision.HELD_MINIMUM_SLEEP,
    WakeDecision.HELD_NO_SLEEP_CONTRACT,
}

@dataclass(frozen=True)
class WakeEnvelope:
    """Peer-authored provenance envelope.

    `reason`, `task`, and `priority` are peer claims. They are authenticated as
    bytes but never become local authority. `priority` is retained only for v0.2
    migration evidence and is deliberately zero-weight. Reply routing is absent:
    reply channels belong in local per-peer configuration.
    """
    protocol: str
    envelope_id: str
    sender: str
    recipient: str
    issued_at: str
    expires_at: str
    nonce: str
    reason: str
    task: str
    priority: int = 50
    key_id: str = 'default'
    signature_alg: str = SIGNATURE_ALG
    signature: str = ''

    @classmethod
    def new(cls, *, sender: str, recipient: str, issued_at: str, expires_at: str, reason: str, task: str, priority: int=50, key_id: str='default', envelope_id: Optional[str]=None, nonce: Optional[str]=None) -> 'WakeEnvelope':
        return cls(protocol=PROTOCOL, envelope_id=envelope_id or str(uuid.uuid4()), sender=sender, recipient=recipient, issued_at=issued_at, expires_at=expires_at, nonce=nonce or uuid.uuid4().hex, reason=reason, task=task, priority=priority, key_id=key_id)

    def unsigned_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data.pop('signature', None)
        return data

    def canonical_bytes(self) -> bytes:
        return canonical_json(self.unsigned_dict()).encode('utf-8')

    def envelope_hash(self) -> str:
        return sha256_json(asdict(self))

    def signed(self, secret: bytes) -> 'WakeEnvelope':
        signature = hmac.new(secret, self.canonical_bytes(), hashlib.sha256).hexdigest()
        data = asdict(self)
        data['signature'] = signature
        return WakeEnvelope(**data)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> 'WakeEnvelope':
        required = {'protocol', 'envelope_id', 'sender', 'recipient', 'issued_at', 'expires_at', 'nonce', 'reason', 'task'}
        missing = sorted(required.difference(value))
        if missing:
            raise ValueError('missing required fields: ' + ', '.join(missing))
        fields = set(cls.__dataclass_fields__)
        unknown = sorted(set(value).difference(fields))
        if unknown:
            raise ValueError('unknown wake-envelope fields: ' + ', '.join(unknown))
        try:
            return cls(**dict(value))
        except TypeError as exc:
            raise ValueError(f'invalid wake envelope: {exc}') from exc

@dataclass(frozen=True)
class SleepContract:
    """Durable lifecycle evidence, never a peer authorization.

    `sleep_note` is annotation only. `unfinished_work` entries must be dated and
    explicitly overridable. Everything not listed in `trusted_without_refresh`
    must be refreshed before action. The authoritative stop-marker path is held
    in immutable local policy; this contract only stamps the stop-policy revision
    that was in force when the session slept.
    """
    sleep_id: str
    agent_id: str
    created_at: str
    rules_revision: str
    model_id: str
    stop_policy_revision: str
    sleep_note: str = ''
    minimum_sleep_until: str = ''
    unfinished_work: Tuple[Mapping[str, Any], ...] = ()
    context_refs: Tuple[str, ...] = ()
    trusted_without_refresh: Tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> 'SleepContract':
        fields = set(cls.__dataclass_fields__)
        unknown = sorted(set(value).difference(fields))
        if unknown:
            raise ValueError('unknown sleep-contract fields: ' + ', '.join(unknown))
        normalized = dict(value)
        for name in ('context_refs', 'trusted_without_refresh'):
            if name in normalized:
                raw = normalized[name]
                if not isinstance(raw, (list, tuple)):
                    raise ValueError(f'sleep contract {name} must be an array')
                normalized[name] = tuple(raw)
        if 'unfinished_work' in normalized:
            raw_work = normalized['unfinished_work']
            if not isinstance(raw_work, (list, tuple)):
                raise ValueError('sleep contract unfinished_work must be an array')
            items = []
            for index, item in enumerate(raw_work):
                if not isinstance(item, Mapping):
                    raise ValueError(f'unfinished_work[{index}] must be an object')
                item_dict = dict(item)
                required = {'ref', 'recorded_at', 'overridable'}
                missing = sorted(required.difference(item_dict))
                unknown_item = sorted(set(item_dict).difference(required))
                if missing:
                    raise ValueError(f'unfinished_work[{index}] missing: ' + ', '.join(missing))
                if unknown_item:
                    raise ValueError(f'unfinished_work[{index}] unknown fields: ' + ', '.join(unknown_item))
                if not isinstance(item_dict['ref'], str) or not item_dict['ref']:
                    raise ValueError(f'unfinished_work[{index}].ref must be non-empty')
                parse_time(item_dict['recorded_at'])
                if item_dict['overridable'] is not True:
                    raise ValueError(f'unfinished_work[{index}] must be explicitly overridable')
                items.append(item_dict)
            normalized['unfinished_work'] = tuple(items)
        try:
            contract = cls(**normalized)
        except TypeError as exc:
            raise ValueError(f'invalid sleep contract: {exc}') from exc
        validate_sleep_contract(contract)
        return contract

@dataclass(frozen=True)
class ComputeLease:
    """Local resource ceiling carried only by a local authorization."""
    max_wall_seconds: int
    max_input_tokens: int
    max_output_tokens: int
    max_tool_calls: int
    max_cost_microusd: int = 0

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> 'ComputeLease':
        fields = set(cls.__dataclass_fields__)
        unknown = sorted(set(value).difference(fields))
        if unknown:
            raise ValueError('unknown compute-lease fields: ' + ', '.join(unknown))
        try:
            lease = cls(**dict(value))
        except TypeError as exc:
            raise ValueError(f'invalid compute lease: {exc}') from exc
        validate_compute_lease(lease)
        return lease

@dataclass(frozen=True)
class IngressPolicy:
    recipient: str
    policy_revision: str
    authorized_senders: Tuple[str, ...]
    valid_request_disposition: str = 'queue'
    max_future_skew_seconds: int = 120

    def validate(self) -> None:
        if not isinstance(self.recipient, str) or not self.recipient:
            raise ValueError('ingress policy recipient must be non-empty')
        if not isinstance(self.policy_revision, str) or not self.policy_revision:
            raise ValueError('ingress policy_revision must be non-empty')
        if not self.authorized_senders:
            raise ValueError('ingress policy authorized_senders must be non-empty')
        if self.valid_request_disposition not in {'queue', 'decline'}:
            raise ValueError('valid_request_disposition must be queue or decline')
        if isinstance(self.max_future_skew_seconds, bool) or not isinstance(self.max_future_skew_seconds, int) or self.max_future_skew_seconds < 0:
            raise ValueError('max_future_skew_seconds must be a non-negative integer')

@dataclass(frozen=True)
class LocalWakePolicy:
    """Local-only authorization policy.

    `mode=queue_only` is the default. `mode=authorize` may only be evaluated on
    an independent local trigger. The peer never supplies this object, the stop
    marker path, the reply route, or the compute lease.
    """
    policy_revision: str
    stop_policy_revision: str
    recipient: str
    mode: str
    authorized_senders: Tuple[str, ...]
    stop_marker_path: str
    authorization_ttl_seconds: int
    compute_lease: ComputeLease
    peer_reply_channels: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> 'LocalWakePolicy':
        fields = set(cls.__dataclass_fields__)
        unknown = sorted(set(value).difference(fields))
        if unknown:
            raise ValueError('unknown local-wake-policy fields: ' + ', '.join(unknown))
        normalized = dict(value)
        raw_senders = normalized.get('authorized_senders', ())
        if not isinstance(raw_senders, (list, tuple)):
            raise ValueError('local policy authorized_senders must be an array')
        normalized['authorized_senders'] = tuple(raw_senders)
        raw_lease = normalized.get('compute_lease')
        if not isinstance(raw_lease, Mapping):
            raise ValueError('local policy compute_lease must be an object')
        normalized['compute_lease'] = ComputeLease.from_mapping(raw_lease)
        raw_channels = normalized.get('peer_reply_channels', {})
        if not isinstance(raw_channels, Mapping):
            raise ValueError('peer_reply_channels must be an object')
        normalized['peer_reply_channels'] = {str(sender): str(channel) for sender, channel in raw_channels.items()}
        try:
            policy = cls(**normalized)
        except TypeError as exc:
            raise ValueError(f'invalid local wake policy: {exc}') from exc
        validate_local_policy(policy)
        return policy

@dataclass(frozen=True)
class WakeAuthorization:
    """Locally signed, short-lived launcher capability."""
    protocol: str
    authorization_id: str
    issued_at: str
    expires_at: str
    recipient: str
    sender: str
    envelope_id: str
    envelope_hash: str
    request_receipt_hash: str
    sleep_id: str
    local_policy_revision: str
    local_policy_hash: str
    rules_revision: str
    declared_model_id: str
    compute_lease: Mapping[str, int]
    key_id: str = 'local-default'
    signature_alg: str = SIGNATURE_ALG
    signature: str = ''

    def unsigned_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data.pop('signature', None)
        return data

    def canonical_bytes(self) -> bytes:
        return canonical_json(self.unsigned_dict()).encode('utf-8')

    def signed(self, secret: bytes) -> 'WakeAuthorization':
        signature = hmac.new(secret, self.canonical_bytes(), hashlib.sha256).hexdigest()
        data = asdict(self)
        data['signature'] = signature
        return WakeAuthorization(**data)

    def authorization_hash(self) -> str:
        return sha256_json(asdict(self))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> 'WakeAuthorization':
        required = {'protocol', 'authorization_id', 'issued_at', 'expires_at', 'recipient', 'sender', 'envelope_id', 'envelope_hash', 'request_receipt_hash', 'sleep_id', 'local_policy_revision', 'local_policy_hash', 'rules_revision', 'declared_model_id', 'compute_lease'}
        missing = sorted(required.difference(value))
        if missing:
            raise ValueError('missing authorization fields: ' + ', '.join(missing))
        fields = set(cls.__dataclass_fields__)
        unknown = sorted(set(value).difference(fields))
        if unknown:
            raise ValueError('unknown authorization fields: ' + ', '.join(unknown))
        raw_lease = value.get('compute_lease')
        if not isinstance(raw_lease, Mapping):
            raise ValueError('authorization compute_lease must be an object')
        ComputeLease.from_mapping(raw_lease)
        try:
            return cls(**dict(value))
        except TypeError as exc:
            raise ValueError(f'invalid wake authorization: {exc}') from exc

@dataclass(frozen=True)
class DecisionResult:
    decision: WakeDecision
    reason: str
    envelope_id: str = ''
    envelope_hash: str = ''
    sender: str = ''
    queue_ref: str = ''
    request_receipt_hash: str = ''
    authorization_ref: str = ''
    authorization_hash: str = ''

    @property
    def should_wake(self) -> bool:
        return self.decision is WakeDecision.WAKE_AUTHORIZED

class Keyring:
    """Maps (sender, key_id) to peer HMAC secret bytes."""

    def __init__(self, keys: Mapping[Tuple[str, str], bytes]):
        self._keys = dict(keys)

    def get(self, sender: str, key_id: str) -> Optional[bytes]:
        return self._keys.get((sender, key_id))

def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)

def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()

def receipt_hash(record: Mapping[str, Any]) -> str:
    unsigned = dict(record)
    unsigned.pop('receipt_hash', None)
    return sha256_json(unsigned)

def parse_time(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError('timestamp must be a non-empty string')
    normalized = value[:-1] + '+00:00' if value.endswith('Z') else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f'invalid ISO-8601 timestamp {value!r}') from exc
    if parsed.tzinfo is None:
        raise ValueError('timestamp must include timezone')
    return parsed.astimezone(timezone.utc)

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

def iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')

def validate_sleep_contract(contract: SleepContract) -> None:
    required_strings = {'sleep_id': contract.sleep_id, 'agent_id': contract.agent_id, 'created_at': contract.created_at, 'rules_revision': contract.rules_revision, 'model_id': contract.model_id, 'stop_policy_revision': contract.stop_policy_revision}
    for name, value in required_strings.items():
        if not isinstance(value, str) or not value:
            raise ValueError(f'sleep contract {name} must be non-empty')
    parse_time(contract.created_at)
    if contract.minimum_sleep_until:
        parse_time(contract.minimum_sleep_until)
    for name, values in (('context_refs', contract.context_refs), ('trusted_without_refresh', contract.trusted_without_refresh)):
        if any((not isinstance(value, str) or not value for value in values)):
            raise ValueError(f'sleep contract {name} entries must be non-empty strings')

def validate_compute_lease(lease: ComputeLease) -> None:
    values = asdict(lease)
    for name, value in values.items():
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f'compute lease {name} must be an integer')
        if value < 0:
            raise ValueError(f'compute lease {name} cannot be negative')
    if lease.max_wall_seconds <= 0:
        raise ValueError('compute lease max_wall_seconds must be positive')
    if lease.max_input_tokens + lease.max_output_tokens <= 0:
        raise ValueError('compute lease must permit at least one token')

def validate_local_policy(policy: LocalWakePolicy) -> None:
    for name, value in (('policy_revision', policy.policy_revision), ('stop_policy_revision', policy.stop_policy_revision), ('recipient', policy.recipient)):
        if not isinstance(value, str) or not value:
            raise ValueError(f'local policy {name} must be non-empty')
    if policy.mode not in {'queue_only', 'decline', 'authorize'}:
        raise ValueError('local policy mode must be queue_only, decline, or authorize')
    if not policy.authorized_senders:
        raise ValueError('local policy authorized_senders must be non-empty')
    marker = Path(policy.stop_marker_path)
    if not marker.is_absolute():
        raise ValueError('stop_marker_path must be absolute')
    if isinstance(policy.authorization_ttl_seconds, bool) or not isinstance(policy.authorization_ttl_seconds, int) or policy.authorization_ttl_seconds <= 0:
        raise ValueError('authorization_ttl_seconds must be a positive integer')
    validate_compute_lease(policy.compute_lease)
    for sender, channel in policy.peer_reply_channels.items():
        if not sender or not channel:
            raise ValueError('peer_reply_channels keys and values must be non-empty')

def verify_peer_signature(envelope: WakeEnvelope, keyring: Keyring) -> Tuple[bool, str]:
    if envelope.signature_alg != SIGNATURE_ALG:
        return (False, f'unsupported signature_alg={envelope.signature_alg}')
    secret = keyring.get(envelope.sender, envelope.key_id)
    if secret is None:
        return (False, 'no trusted key for sender/key_id')
    expected = hmac.new(secret, envelope.canonical_bytes(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, envelope.signature):
        return (False, 'signature mismatch')
    return (True, 'signature verified')

def verify_local_authorization(authorization: WakeAuthorization, secret: bytes, *, recipient: Optional[str]=None, now: Optional[datetime]=None) -> Tuple[bool, str]:
    if authorization.protocol != AUTHORIZATION_PROTOCOL:
        return (False, f'unsupported authorization protocol={authorization.protocol}')
    if authorization.signature_alg != SIGNATURE_ALG:
        return (False, f'unsupported signature_alg={authorization.signature_alg}')
    if recipient is not None and authorization.recipient != recipient:
        return (False, f'expected recipient={recipient}')
    try:
        issued_at = parse_time(authorization.issued_at)
        expires_at = parse_time(authorization.expires_at)
    except ValueError as exc:
        return (False, str(exc))
    observed = (now or utc_now()).astimezone(timezone.utc)
    if expires_at <= issued_at:
        return (False, 'authorization expires_at must be after issued_at')
    if observed >= expires_at:
        return (False, 'authorization expired')
    expected = hmac.new(secret, authorization.canonical_bytes(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, authorization.signature):
        return (False, 'authorization signature mismatch')
    return (True, 'authorization verified')

def _base_result(envelope: WakeEnvelope, decision: WakeDecision, reason: str) -> DecisionResult:
    return DecisionResult(decision=decision, reason=reason, envelope_id=str(envelope.envelope_id), envelope_hash=envelope.envelope_hash(), sender=str(envelope.sender))
