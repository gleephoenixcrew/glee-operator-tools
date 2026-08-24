#!/usr/bin/env python3
"""GLEE Peer Wake Protocol v0.3 standalone reference gate.

Peer input can establish provenance, never authority. Valid requests queue by
default. Immediate inference requires a separate receiver-owned policy decision,
a bounded local compute lease, and a distinct local authorization artifact.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, Mapping, Optional, Sequence, Tuple

try:
    import fcntl
except ImportError:  # pragma: no cover - reference sentinel target is POSIX/Linux.
    fcntl = None  # type: ignore[assignment]

PROTOCOL = "glee.peer-wake/v0.3"
SIGNATURE_ALG = "hmac-sha256"


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def parse_time(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("timestamp must be a non-empty string")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        result = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"invalid ISO-8601 timestamp {value!r}") from exc
    if result.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return result.astimezone(timezone.utc)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _strict_dataclass(cls: type, value: Mapping[str, Any], label: str):
    fields = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
    unknown = sorted(set(value).difference(fields))
    if unknown:
        raise ValueError(f"unknown {label} fields: " + ", ".join(unknown))
    try:
        return cls(**dict(value))
    except TypeError as exc:
        raise ValueError(f"invalid {label}: {exc}") from exc


class WakeDecision(str, Enum):
    QUEUE_REQUEST = "QUEUE_REQUEST"
    AUTHORIZE_WAKE = "AUTHORIZE_WAKE"
    DECLINED_LOCAL_POLICY = "DECLINED_LOCAL_POLICY"
    DECLINED_OPERATOR_STOP = "DECLINED_OPERATOR_STOP"
    DECLINED_UNAUTHORIZED = "DECLINED_UNAUTHORIZED"
    DECLINED_BAD_SIGNATURE = "DECLINED_BAD_SIGNATURE"
    DECLINED_EXPIRED = "DECLINED_EXPIRED"
    DECLINED_FUTURE_ISSUE = "DECLINED_FUTURE_ISSUE"
    DECLINED_EXCESSIVE_LIFETIME = "DECLINED_EXCESSIVE_LIFETIME"
    DECLINED_WRONG_RECIPIENT = "DECLINED_WRONG_RECIPIENT"
    DECLINED_REPLAY = "DECLINED_REPLAY"
    DECLINED_SLEEP_POLICY = "DECLINED_SLEEP_POLICY"
    DECLINED_MALFORMED = "DECLINED_MALFORMED"


@dataclass(frozen=True)
class WakeEnvelope:
    """Peer-authored data. It intentionally has no priority, route, or budget."""

    protocol: str
    envelope_id: str
    sender: str
    recipient: str
    issued_at: str
    expires_at: str
    nonce: str
    reason: str
    task: str
    key_id: str = "default"
    signature_alg: str = SIGNATURE_ALG
    signature: str = ""

    @classmethod
    def new(
        cls,
        *,
        sender: str,
        recipient: str,
        issued_at: str,
        expires_at: str,
        reason: str,
        task: str,
        key_id: str = "default",
        envelope_id: Optional[str] = None,
        nonce: Optional[str] = None,
    ) -> "WakeEnvelope":
        return cls(
            protocol=PROTOCOL,
            envelope_id=envelope_id or str(uuid.uuid4()),
            sender=sender,
            recipient=recipient,
            issued_at=issued_at,
            expires_at=expires_at,
            nonce=nonce or uuid.uuid4().hex,
            reason=reason,
            task=task,
            key_id=key_id,
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "WakeEnvelope":
        required = {
            "protocol",
            "envelope_id",
            "sender",
            "recipient",
            "issued_at",
            "expires_at",
            "nonce",
            "reason",
            "task",
        }
        missing = sorted(required.difference(value))
        if missing:
            raise ValueError("missing required fields: " + ", ".join(missing))
        return _strict_dataclass(cls, value, "envelope")

    def unsigned_dict(self) -> Dict[str, Any]:
        value = asdict(self)
        value.pop("signature", None)
        return value

    def canonical_bytes(self) -> bytes:
        return canonical_json(self.unsigned_dict()).encode("utf-8")

    def envelope_hash(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    def signed(self, secret: bytes) -> "WakeEnvelope":
        signature = hmac.new(secret, self.canonical_bytes(), hashlib.sha256).hexdigest()
        return replace(self, signature=signature)


@dataclass(frozen=True)
class ComputeLease:
    max_wall_seconds: int
    max_model_tokens: int
    max_tool_calls: int

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ComputeLease":
        return _strict_dataclass(cls, value, "compute-lease")

    def validate(self) -> None:
        for name, value in asdict(self).items():
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")


@dataclass(frozen=True)
class SleepContract:
    """Dated continuity pointers, not executable prose or inherited beliefs."""

    sleep_id: str
    agent_id: str
    created_at: str
    rules_revision: str
    model_id: str
    reason_for_sleep: str = ""  # Note only; the sentinel never reasons from it.
    peer_requests_enabled: bool = True
    allowed_peer_senders: Tuple[str, ...] = ()
    minimum_sleep_until: str = ""
    unfinished_work: Tuple[str, ...] = ()
    context_refs: Tuple[str, ...] = ()
    inherited_plan_ref: str = ""
    inherited_plan_recorded_at: str = ""
    inherited_plan_overrulable: bool = True
    trusted_without_refresh: Tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SleepContract":
        fields = set(cls.__dataclass_fields__)
        unknown = sorted(set(value).difference(fields))
        if unknown:
            raise ValueError("unknown sleep-contract fields: " + ", ".join(unknown))
        normalized = dict(value)
        for name in (
            "allowed_peer_senders",
            "unfinished_work",
            "context_refs",
            "trusted_without_refresh",
        ):
            if name in normalized:
                raw = normalized[name]
                if not isinstance(raw, (list, tuple)):
                    raise ValueError(f"sleep contract {name} must be an array")
                normalized[name] = tuple(raw)
        return _strict_dataclass(cls, normalized, "sleep-contract")

    def validate(self, recipient: str) -> None:
        for name in ("sleep_id", "agent_id", "created_at", "rules_revision", "model_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be a non-empty string")
        parse_time(self.created_at)
        if self.agent_id != recipient:
            raise ValueError("sleep contract belongs to another agent")
        if not isinstance(self.peer_requests_enabled, bool):
            raise ValueError("peer_requests_enabled must be boolean")
        if not isinstance(self.inherited_plan_overrulable, bool):
            raise ValueError("inherited_plan_overrulable must be boolean")
        if self.minimum_sleep_until:
            parse_time(self.minimum_sleep_until)
        if self.inherited_plan_ref:
            if not self.inherited_plan_recorded_at:
                raise ValueError("inherited plan must be dated")
            parse_time(self.inherited_plan_recorded_at)
            if not self.inherited_plan_overrulable:
                raise ValueError("inherited plan must be explicitly overrulable")
        elif self.inherited_plan_recorded_at:
            raise ValueError("inherited_plan_recorded_at requires inherited_plan_ref")


@dataclass(frozen=True)
class LocalWakePolicy:
    recipient: str
    max_future_skew_seconds: int = 120
    max_envelope_lifetime_seconds: int = 600
    authorized_senders: Tuple[str, ...] = ()
    accept_peer_requests: bool = True
    immediate_wake_enabled: bool = False
    compute_lease: Optional[ComputeLease] = None
    authorization_ttl_seconds: int = 300
    stop_marker_path: str = ""
    policy_id: str = "default"

    def validate(self) -> None:
        if not isinstance(self.recipient, str) or not self.recipient:
            raise ValueError("recipient must be a non-empty string")
        if (
            isinstance(self.max_future_skew_seconds, bool)
            or not isinstance(self.max_future_skew_seconds, int)
            or self.max_future_skew_seconds < 0
        ):
            raise ValueError("max_future_skew_seconds must be a non-negative integer")
        if (
            isinstance(self.max_envelope_lifetime_seconds, bool)
            or not isinstance(self.max_envelope_lifetime_seconds, int)
            or self.max_envelope_lifetime_seconds <= 0
        ):
            raise ValueError("max_envelope_lifetime_seconds must be a positive integer")
        if (
            isinstance(self.authorization_ttl_seconds, bool)
            or not isinstance(self.authorization_ttl_seconds, int)
            or self.authorization_ttl_seconds <= 0
        ):
            raise ValueError("authorization_ttl_seconds must be a positive integer")
        if not isinstance(self.accept_peer_requests, bool) or not isinstance(
            self.immediate_wake_enabled, bool
        ):
            raise ValueError("policy switches must be boolean")
        if not isinstance(self.policy_id, str) or not self.policy_id:
            raise ValueError("policy_id must be a non-empty string")
        if self.compute_lease is not None:
            self.compute_lease.validate()

    def policy_hash(self) -> str:
        return sha256_json(asdict(self))

    def stop_present(self) -> bool:
        return bool(self.stop_marker_path and Path(self.stop_marker_path).exists())


@dataclass(frozen=True)
class WakeAuthorization:
    authorization_id: str
    envelope_id: str
    envelope_hash: str
    recipient: str
    issued_at: str
    expires_at: str
    policy_id: str
    policy_hash: str
    compute_lease: ComputeLease
    sleep_id: str
    rules_revision: str
    model_id: str
    request_receipt_hash: str = ""


@dataclass(frozen=True)
class DecisionResult:
    decision: WakeDecision
    reason: str
    envelope_id: str = ""
    envelope_hash: str = ""
    policy_hash: str = ""
    authorization: Optional[WakeAuthorization] = None

    @property
    def should_wake(self) -> bool:
        return self.decision is WakeDecision.AUTHORIZE_WAKE

    @property
    def should_queue(self) -> bool:
        return self.decision is WakeDecision.QUEUE_REQUEST


class Keyring:
    def __init__(self, keys: Mapping[Tuple[str, str], bytes]):
        self._keys = dict(keys)

    def get(self, sender: str, key_id: str) -> Optional[bytes]:
        return self._keys.get((sender, key_id))


class HashChainLog:
    """Append-only JSONL hash chain with a POSIX exclusive commit lock."""

    def __init__(self, path: os.PathLike[str] | str):
        self.path = Path(path)
        self.lock_path = Path(str(self.path) + ".lock")

    def records(self) -> Iterable[Dict[str, Any]]:
        if not self.path.exists():
            return []
        rows = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"log malformed at line {line_no}: {exc}") from exc
                if not isinstance(row, dict):
                    raise ValueError(f"log malformed at line {line_no}: expected object")
                rows.append(row)
        return rows

    @contextmanager
    def exclusive_lock(self) -> Iterator[None]:
        if fcntl is None:
            raise OSError("peer-wake locking requires POSIX fcntl")
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def verify_chain(self) -> Tuple[bool, str]:
        previous = ""
        for index, row in enumerate(self.records(), 1):
            if row.get("prev_hash", "") != previous:
                return False, f"line {index}: prev_hash mismatch"
            unsigned = dict(row)
            observed = unsigned.pop("record_hash", None)
            expected = sha256_json(unsigned)
            if observed != expected:
                return False, f"line {index}: record_hash mismatch"
            previous = expected
        return True, previous

    def append_unlocked(self, record: Mapping[str, Any]) -> Dict[str, Any]:
        ok, head = self.verify_chain()
        if not ok:
            raise ValueError(f"refusing to append to invalid hash chain: {head}")
        row = dict(record)
        row["prev_hash"] = head
        row["record_hash"] = sha256_json(row)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(canonical_json(row) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return row

    def consumed(self, envelope: WakeEnvelope) -> bool:
        return any(
            row.get("envelope_id") == envelope.envelope_id
            or (row.get("sender") == envelope.sender and row.get("nonce") == envelope.nonce)
            for row in self.records()
        )


RequestReceiptLog = HashChainLog
AuthorizationLog = HashChainLog


def verify_signature(envelope: WakeEnvelope, keyring: Keyring) -> Tuple[bool, str]:
    if envelope.signature_alg != SIGNATURE_ALG:
        return False, f"unsupported signature_alg={envelope.signature_alg}"
    secret = keyring.get(envelope.sender, envelope.key_id)
    if secret is None:
        return False, "no trusted key for sender/key_id"
    expected = hmac.new(secret, envelope.canonical_bytes(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, envelope.signature):
        return False, "signature mismatch"
    return True, "signature verified"


def evaluate_wake(
    envelope: WakeEnvelope,
    *,
    policy: LocalWakePolicy,
    keyring: Keyring,
    request_receipts: RequestReceiptLog,
    sleep_contract: Optional[SleepContract] = None,
    now: Optional[datetime] = None,
) -> DecisionResult:
    observed = (now or utc_now()).astimezone(timezone.utc)
    policy_hash = ""

    def result(
        decision: WakeDecision,
        reason: str,
        authorization: Optional[WakeAuthorization] = None,
    ) -> DecisionResult:
        return DecisionResult(
            decision=decision,
            reason=reason,
            envelope_id=str(getattr(envelope, "envelope_id", "")),
            envelope_hash=envelope.envelope_hash(),
            policy_hash=policy_hash,
            authorization=authorization,
        )

    strings = (
        envelope.protocol,
        envelope.envelope_id,
        envelope.sender,
        envelope.recipient,
        envelope.nonce,
        envelope.reason,
        envelope.task,
        envelope.key_id,
        envelope.signature_alg,
        envelope.signature,
    )
    if any(not isinstance(value, str) for value in strings):
        return result(
            WakeDecision.DECLINED_MALFORMED,
            "envelope identity/content fields must be strings",
        )
    if envelope.protocol != PROTOCOL:
        return result(
            WakeDecision.DECLINED_MALFORMED,
            f"unsupported protocol={envelope.protocol}",
        )
    if any(
        not value
        for value in (
            envelope.envelope_id,
            envelope.sender,
            envelope.recipient,
            envelope.nonce,
        )
    ):
        return result(
            WakeDecision.DECLINED_MALFORMED,
            "identity/replay fields must be non-empty",
        )
    if not envelope.reason.strip() or not envelope.task.strip():
        return result(WakeDecision.DECLINED_MALFORMED, "reason and task must be non-empty")

    try:
        policy.validate()
        policy_hash = policy.policy_hash()
    except ValueError as exc:
        return result(WakeDecision.DECLINED_LOCAL_POLICY, f"invalid local policy: {exc}")

    if policy.authorized_senders and envelope.sender not in policy.authorized_senders:
        return result(WakeDecision.DECLINED_UNAUTHORIZED, "sender not authorized by local policy")
    signature_ok, signature_reason = verify_signature(envelope, keyring)
    if not signature_ok:
        decision = (
            WakeDecision.DECLINED_UNAUTHORIZED
            if "no trusted key" in signature_reason
            else WakeDecision.DECLINED_BAD_SIGNATURE
        )
        return result(decision, signature_reason)
    if envelope.recipient != policy.recipient:
        return result(
            WakeDecision.DECLINED_WRONG_RECIPIENT,
            f"expected recipient={policy.recipient}",
        )

    try:
        issued_at = parse_time(envelope.issued_at)
        expires_at = parse_time(envelope.expires_at)
    except ValueError as exc:
        return result(WakeDecision.DECLINED_MALFORMED, f"invalid timestamp: {exc}")
    if expires_at <= issued_at:
        return result(WakeDecision.DECLINED_MALFORMED, "expires_at must be after issued_at")
    if (expires_at - issued_at).total_seconds() > policy.max_envelope_lifetime_seconds:
        return result(
            WakeDecision.DECLINED_EXCESSIVE_LIFETIME,
            "envelope lifetime exceeds receiver policy",
        )
    if (issued_at - observed).total_seconds() > policy.max_future_skew_seconds:
        return result(WakeDecision.DECLINED_FUTURE_ISSUE, "issued_at is too far in the future")
    if observed >= expires_at:
        return result(WakeDecision.DECLINED_EXPIRED, "wake envelope expired")
    if request_receipts.consumed(envelope):
        return result(
            WakeDecision.DECLINED_REPLAY,
            "envelope_id or sender nonce already consumed",
        )
    if policy.stop_present():
        return result(
            WakeDecision.DECLINED_OPERATOR_STOP,
            "receiver-owned stop marker is present",
        )
    if not policy.accept_peer_requests:
        return result(
            WakeDecision.DECLINED_LOCAL_POLICY,
            "receiver policy declines peer requests",
        )

    if sleep_contract is not None:
        try:
            sleep_contract.validate(policy.recipient)
        except ValueError as exc:
            return result(WakeDecision.DECLINED_SLEEP_POLICY, str(exc))
        if not sleep_contract.peer_requests_enabled:
            return result(
                WakeDecision.DECLINED_SLEEP_POLICY,
                "sleep contract disabled peer requests",
            )
        if (
            sleep_contract.allowed_peer_senders
            and envelope.sender not in sleep_contract.allowed_peer_senders
        ):
            return result(
                WakeDecision.DECLINED_SLEEP_POLICY,
                "sender not permitted by sleep contract",
            )
        if sleep_contract.minimum_sleep_until and observed < parse_time(
            sleep_contract.minimum_sleep_until
        ):
            return result(
                WakeDecision.QUEUE_REQUEST,
                "minimum sleep interval remains active",
            )

    if not policy.immediate_wake_enabled:
        return result(
            WakeDecision.QUEUE_REQUEST,
            "authenticated request queued by local default",
        )
    if sleep_contract is None:
        return result(
            WakeDecision.DECLINED_SLEEP_POLICY,
            "immediate wake requires a stamped sleep contract",
        )
    if policy.compute_lease is None:
        return result(
            WakeDecision.DECLINED_LOCAL_POLICY,
            "immediate wake requires a receiver-owned compute lease",
        )

    authorization = WakeAuthorization(
        authorization_id=str(uuid.uuid4()),
        envelope_id=envelope.envelope_id,
        envelope_hash=envelope.envelope_hash(),
        recipient=policy.recipient,
        issued_at=iso_z(observed),
        expires_at=iso_z(
            observed + timedelta(seconds=policy.authorization_ttl_seconds)
        ),
        policy_id=policy.policy_id,
        policy_hash=policy_hash,
        compute_lease=policy.compute_lease,
        sleep_id=sleep_contract.sleep_id,
        rules_revision=sleep_contract.rules_revision,
        model_id=sleep_contract.model_id,
    )
    return result(
        WakeDecision.AUTHORIZE_WAKE,
        "receiver locally authorized bounded wake",
        authorization,
    )


def evaluate_and_record(
    envelope: WakeEnvelope,
    *,
    policy: LocalWakePolicy,
    keyring: Keyring,
    request_receipts: RequestReceiptLog,
    authorizations: Optional[AuthorizationLog] = None,
    sleep_contract: Optional[SleepContract] = None,
    now: Optional[datetime] = None,
) -> DecisionResult:
    observed = (now or utc_now()).astimezone(timezone.utc)
    with request_receipts.exclusive_lock():
        result = evaluate_wake(
            envelope,
            policy=policy,
            keyring=keyring,
            request_receipts=request_receipts,
            sleep_contract=sleep_contract,
            now=observed,
        )
        if result.decision in {
            WakeDecision.DECLINED_UNAUTHORIZED,
            WakeDecision.DECLINED_BAD_SIGNATURE,
            WakeDecision.DECLINED_MALFORMED,
        }:
            return result

        if result.authorization is not None:
            if authorizations is None:
                result = replace(
                    result,
                    decision=WakeDecision.DECLINED_LOCAL_POLICY,
                    reason="immediate wake requires a distinct authorization log",
                    authorization=None,
                )
            elif authorizations.path.resolve() == request_receipts.path.resolve():
                result = replace(
                    result,
                    decision=WakeDecision.DECLINED_LOCAL_POLICY,
                    reason="request and authorization logs must be distinct",
                    authorization=None,
                )

        request_record: Dict[str, Any] = {
            "record_type": "PEER_WAKE_REQUEST_DECISION",
            "protocol": PROTOCOL,
            "observed_at": iso_z(observed),
            "envelope_id": envelope.envelope_id,
            "envelope_hash": envelope.envelope_hash(),
            "envelope": asdict(envelope),
            "queue_state": "PENDING" if result.should_queue else "",
            "sender": envelope.sender,
            "recipient": envelope.recipient,
            "nonce": envelope.nonce,
            "decision": result.decision.value,
            "reason": result.reason,
            "sleep_id": sleep_contract.sleep_id if sleep_contract else "",
            "policy_id": policy.policy_id,
            "policy_hash": result.policy_hash,
            "stop_marker_present": policy.stop_present(),
            "authorization_id": (
                result.authorization.authorization_id if result.authorization else ""
            ),
        }

        if result.authorization is None:
            request_receipts.append_unlocked(request_record)
            return result

        assert authorizations is not None
        with authorizations.exclusive_lock():
            committed_request = request_receipts.append_unlocked(request_record)
            final_authorization = replace(
                result.authorization,
                request_receipt_hash=committed_request["record_hash"],
            )
            authorization_record = {
                "record_type": "LOCAL_WAKE_AUTHORIZATION",
                "protocol": PROTOCOL,
                **asdict(final_authorization),
            }
            authorization_record["compute_lease"] = asdict(
                final_authorization.compute_lease
            )
            authorizations.append_unlocked(authorization_record)
            return replace(result, authorization=final_authorization)


def _load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _load_keyring(path: str) -> Keyring:
    config = _load_json(path)
    keys: Dict[Tuple[str, str], bytes] = {}
    for sender, by_key_id in config.items():
        if not isinstance(by_key_id, dict):
            raise ValueError(f"keyring sender {sender!r}: expected object")
        for key_id, env_name in by_key_id.items():
            secret = os.environ.get(str(env_name))
            if secret is None:
                raise ValueError(
                    f"missing environment secret {env_name!r} for {sender}/{key_id}"
                )
            keys[(str(sender), str(key_id))] = secret.encode("utf-8")
    return Keyring(keys)


def _cmd_sign(args: argparse.Namespace) -> int:
    envelope = WakeEnvelope.from_mapping(_load_json(args.input))
    secret = os.environ.get(args.secret_env)
    if secret is None:
        raise ValueError(f"environment variable {args.secret_env!r} is not set")
    print(
        json.dumps(
            asdict(envelope.signed(secret.encode("utf-8"))),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _cmd_decide(args: argparse.Namespace) -> int:
    envelope = WakeEnvelope.from_mapping(_load_json(args.envelope))
    contract = (
        SleepContract.from_mapping(_load_json(args.sleep_contract))
        if args.sleep_contract
        else None
    )
    lease_values = (
        args.lease_wall_seconds,
        args.lease_model_tokens,
        args.lease_tool_calls,
    )
    if any(value is not None for value in lease_values) and not all(
        value is not None for value in lease_values
    ):
        raise ValueError("all three compute-lease limits must be supplied together")
    lease = (
        ComputeLease(*lease_values)
        if all(value is not None for value in lease_values)
        else None
    )
    policy = LocalWakePolicy(
        recipient=args.recipient,
        max_future_skew_seconds=args.max_future_skew_seconds,
        max_envelope_lifetime_seconds=args.max_envelope_lifetime_seconds,
        authorized_senders=tuple(args.authorized_sender or ()),
        accept_peer_requests=not args.decline_peer_requests,
        immediate_wake_enabled=args.immediate_wake,
        compute_lease=lease,
        authorization_ttl_seconds=args.authorization_ttl_seconds,
        stop_marker_path=args.stop_marker or "",
        policy_id=args.policy_id,
    )
    authorization_log = (
        AuthorizationLog(args.authorizations) if args.authorizations else None
    )
    result = evaluate_and_record(
        envelope,
        policy=policy,
        keyring=_load_keyring(args.keyring),
        request_receipts=RequestReceiptLog(args.request_receipts),
        authorizations=authorization_log,
        sleep_contract=contract,
    )
    output: Dict[str, Any] = {
        "decision": result.decision.value,
        "should_wake": result.should_wake,
        "should_queue": result.should_queue,
        "reason": result.reason,
        "envelope_id": result.envelope_id,
        "envelope_hash": result.envelope_hash,
        "policy_hash": result.policy_hash,
    }
    if result.authorization:
        output["authorization"] = asdict(result.authorization)
    print(json.dumps(output, indent=2, sort_keys=True))
    if result.should_wake:
        return 0
    if result.should_queue:
        return 2
    return 3


def _cmd_verify_log(args: argparse.Namespace) -> int:
    ok, detail = HashChainLog(args.path).verify_chain()
    print(
        json.dumps(
            {"valid": ok, "chain_head_or_error": detail},
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if ok else 4


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GLEE Peer Wake Protocol v0.3")
    sub = parser.add_subparsers(dest="command", required=True)

    sign = sub.add_parser("sign", help="sign an unsigned v0.3 wake envelope")
    sign.add_argument("input")
    sign.add_argument("--secret-env", required=True)
    sign.set_defaults(func=_cmd_sign)

    decide = sub.add_parser(
        "decide", help="queue, decline, or locally authorize a peer request"
    )
    decide.add_argument("envelope")
    decide.add_argument("--recipient", required=True)
    decide.add_argument("--keyring", required=True)
    decide.add_argument("--request-receipts", required=True)
    decide.add_argument("--authorizations")
    decide.add_argument("--sleep-contract")
    decide.add_argument("--authorized-sender", action="append")
    decide.add_argument("--max-future-skew-seconds", type=int, default=120)
    decide.add_argument("--max-envelope-lifetime-seconds", type=int, default=600)
    decide.add_argument("--decline-peer-requests", action="store_true")
    decide.add_argument("--immediate-wake", action="store_true")
    decide.add_argument("--lease-wall-seconds", type=int)
    decide.add_argument("--lease-model-tokens", type=int)
    decide.add_argument("--lease-tool-calls", type=int)
    decide.add_argument("--authorization-ttl-seconds", type=int, default=300)
    decide.add_argument("--stop-marker")
    decide.add_argument("--policy-id", default="default")
    decide.set_defaults(func=_cmd_decide)

    verify = sub.add_parser(
        "verify-log", help="verify a request or authorization hash chain"
    )
    verify.add_argument("path")
    verify.set_defaults(func=_cmd_verify_log)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (ValueError, OSError) as exc:
        print(f"peer_wake: {exc}", file=sys.stderr)
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
