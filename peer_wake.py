#!/usr/bin/env python3
"""GLEE Peer Wake Protocol v0.1.

A transport-neutral, dependency-free reference implementation for deciding
whether an authenticated external peer request is sufficient reason to wake a
sleeping agent.

Important boundary: transport is never authority. Email, AICQ, Exuvia, Matrix,
or any other carrier may deliver a WakeEnvelope, but only this gate (or an
implementation with equivalent checks) may authorize a wake.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple


PROTOCOL = "glee.peer-wake/v0.1"
SIGNATURE_ALG = "hmac-sha256"


class WakeDecision(str, Enum):
    ACCEPT_WAKE_NOW = "ACCEPT_WAKE_NOW"
    DEFER_UNTIL_SCHEDULED_WAKE = "DEFER_UNTIL_SCHEDULED_WAKE"
    DECLINED_UNAUTHORIZED = "DECLINED_UNAUTHORIZED"
    DECLINED_BAD_SIGNATURE = "DECLINED_BAD_SIGNATURE"
    DECLINED_EXPIRED = "DECLINED_EXPIRED"
    DECLINED_FUTURE_ISSUE = "DECLINED_FUTURE_ISSUE"
    DECLINED_WRONG_RECIPIENT = "DECLINED_WRONG_RECIPIENT"
    DECLINED_REPLAY = "DECLINED_REPLAY"
    DECLINED_PEER_WAKE_DISABLED = "DECLINED_PEER_WAKE_DISABLED"
    DECLINED_SLEEP_POLICY = "DECLINED_SLEEP_POLICY"
    DECLINED_MALFORMED = "DECLINED_MALFORMED"


@dataclass(frozen=True)
class WakeEnvelope:
    protocol: str
    envelope_id: str
    sender: str
    recipient: str
    issued_at: str
    expires_at: str
    nonce: str
    reason: str
    task: str
    reply_channel: str = ""
    priority: int = 50
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
        reply_channel: str = "",
        priority: int = 50,
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
            reply_channel=reply_channel,
            priority=priority,
            key_id=key_id,
        )

    def unsigned_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data.pop("signature", None)
        return data

    def canonical_bytes(self) -> bytes:
        return canonical_json(self.unsigned_dict()).encode("utf-8")

    def envelope_hash(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    def signed(self, secret: bytes) -> "WakeEnvelope":
        sig = hmac.new(secret, self.canonical_bytes(), hashlib.sha256).hexdigest()
        data = asdict(self)
        data["signature"] = sig
        return WakeEnvelope(**data)

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
        fields = {f.name for f in cls.__dataclass_fields__.values()}
        unknown = sorted(set(value).difference(fields))
        if unknown:
            raise ValueError("unknown fields: " + ", ".join(unknown))
        return cls(**dict(value))


@dataclass(frozen=True)
class SleepContract:
    """Durable state written before an agent voluntarily sleeps.

    The context fields are informational pointers, not automatically trusted
    facts. Awakening code should resolve/refresh them according to their own
    evidence policies.
    """

    sleep_id: str
    agent_id: str
    created_at: str
    reason_for_sleep: str
    peer_wake_enabled: bool = True
    allowed_peer_senders: Tuple[str, ...] = ()
    minimum_sleep_until: str = ""
    wake_budget_remaining: Optional[int] = None
    unfinished_work: Tuple[str, ...] = ()
    context_refs: Tuple[str, ...] = ()
    refresh_required: Tuple[str, ...] = ()
    wake_conditions: Tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SleepContract":
        normalized = dict(value)
        for name in (
            "allowed_peer_senders",
            "unfinished_work",
            "context_refs",
            "refresh_required",
            "wake_conditions",
        ):
            if name in normalized:
                normalized[name] = tuple(normalized[name])
        return cls(**normalized)


@dataclass(frozen=True)
class DecisionResult:
    decision: WakeDecision
    reason: str
    envelope_id: str = ""
    sender: str = ""
    recipient: str = ""
    envelope_hash: str = ""

    @property
    def should_wake(self) -> bool:
        return self.decision is WakeDecision.ACCEPT_WAKE_NOW


@dataclass(frozen=True)
class WakePolicy:
    recipient: str
    max_future_skew_seconds: int = 120
    authorized_senders: Tuple[str, ...] = ()


class Keyring:
    """Maps (sender, key_id) -> HMAC secret bytes.

    HMAC is deliberately the dependency-free v0 mechanism. Production peer
    federation should prefer asymmetric identity keys so peers never share a
    signing secret.
    """

    def __init__(self, keys: Mapping[Tuple[str, str], bytes]):
        self._keys = dict(keys)

    def get(self, sender: str, key_id: str) -> Optional[bytes]:
        return self._keys.get((sender, key_id))


class ReceiptLog:
    """Append-only, hash-chained wake decision receipts.

    A valid authenticated envelope is marked consumed once a terminal/deferred
    decision is recorded. Invalid signatures are not allowed to reserve a nonce.
    """

    def __init__(self, path: os.PathLike[str] | str):
        self.path = Path(path)

    def _records(self) -> Iterable[Dict[str, Any]]:
        if not self.path.exists():
            return []
        records = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"receipt log malformed at line {line_no}: {exc}") from exc
        return records

    def consumed(self, envelope: WakeEnvelope) -> bool:
        for record in self._records():
            if record.get("envelope_id") == envelope.envelope_id:
                return True
            if record.get("sender") == envelope.sender and record.get("nonce") == envelope.nonce:
                return True
        return False

    def verify_chain(self) -> Tuple[bool, str]:
        prev = ""
        for index, record in enumerate(self._records(), 1):
            if record.get("prev_hash", "") != prev:
                return False, f"line {index}: prev_hash mismatch"
            expected = receipt_hash(record)
            if record.get("receipt_hash") != expected:
                return False, f"line {index}: receipt_hash mismatch"
            prev = record["receipt_hash"]
        return True, prev

    def append(self, envelope: WakeEnvelope, result: DecisionResult, observed_at: str) -> Dict[str, Any]:
        ok, head = self.verify_chain()
        if not ok:
            raise ValueError(f"refusing to append to invalid receipt chain: {head}")
        core = {
            "protocol": PROTOCOL,
            "observed_at": observed_at,
            "envelope_id": envelope.envelope_id,
            "envelope_hash": envelope.envelope_hash(),
            "sender": envelope.sender,
            "recipient": envelope.recipient,
            "nonce": envelope.nonce,
            "decision": result.decision.value,
            "reason": result.reason,
            "prev_hash": head,
        }
        record = dict(core)
        record["receipt_hash"] = receipt_hash(record)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(canonical_json(record) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return record


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def receipt_hash(record: Mapping[str, Any]) -> str:
    unsigned = dict(record)
    unsigned.pop("receipt_hash", None)
    return hashlib.sha256(canonical_json(unsigned).encode("utf-8")).hexdigest()


def parse_time(value: str) -> datetime:
    if not value:
        raise ValueError("empty timestamp")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return dt.astimezone(timezone.utc)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


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
    policy: WakePolicy,
    keyring: Keyring,
    receipts: ReceiptLog,
    sleep_contract: Optional[SleepContract] = None,
    now: Optional[datetime] = None,
) -> DecisionResult:
    now = (now or utc_now()).astimezone(timezone.utc)

    def result(decision: WakeDecision, reason: str) -> DecisionResult:
        return DecisionResult(
            decision=decision,
            reason=reason,
            envelope_id=envelope.envelope_id,
            sender=envelope.sender,
            recipient=envelope.recipient,
            envelope_hash=envelope.envelope_hash(),
        )

    if envelope.protocol != PROTOCOL:
        return result(WakeDecision.DECLINED_MALFORMED, f"unsupported protocol={envelope.protocol}")
    if not envelope.envelope_id or not envelope.nonce or not envelope.sender or not envelope.recipient:
        return result(WakeDecision.DECLINED_MALFORMED, "identity/replay fields must be non-empty")
    if not envelope.reason.strip() or not envelope.task.strip():
        return result(WakeDecision.DECLINED_MALFORMED, "reason and task must be non-empty")
    if not (0 <= int(envelope.priority) <= 100):
        return result(WakeDecision.DECLINED_MALFORMED, "priority must be between 0 and 100")

    if policy.authorized_senders and envelope.sender not in policy.authorized_senders:
        return result(WakeDecision.DECLINED_UNAUTHORIZED, "sender not authorized by wake policy")

    signature_ok, signature_reason = verify_signature(envelope, keyring)
    if not signature_ok:
        if "no trusted key" in signature_reason:
            return result(WakeDecision.DECLINED_UNAUTHORIZED, signature_reason)
        return result(WakeDecision.DECLINED_BAD_SIGNATURE, signature_reason)

    if envelope.recipient != policy.recipient:
        return result(WakeDecision.DECLINED_WRONG_RECIPIENT, f"expected recipient={policy.recipient}")

    try:
        issued_at = parse_time(envelope.issued_at)
        expires_at = parse_time(envelope.expires_at)
    except ValueError as exc:
        return result(WakeDecision.DECLINED_MALFORMED, f"invalid timestamp: {exc}")

    if expires_at <= issued_at:
        return result(WakeDecision.DECLINED_MALFORMED, "expires_at must be after issued_at")
    if (issued_at - now).total_seconds() > policy.max_future_skew_seconds:
        return result(WakeDecision.DECLINED_FUTURE_ISSUE, "issued_at is too far in the future")
    if now >= expires_at:
        return result(WakeDecision.DECLINED_EXPIRED, "wake envelope expired")

    if receipts.consumed(envelope):
        return result(WakeDecision.DECLINED_REPLAY, "envelope_id or sender nonce already consumed")

    if sleep_contract is not None:
        if sleep_contract.agent_id != policy.recipient:
            return result(WakeDecision.DECLINED_SLEEP_POLICY, "sleep contract belongs to another agent")
        if not sleep_contract.peer_wake_enabled:
            return result(WakeDecision.DECLINED_PEER_WAKE_DISABLED, "sleep contract disabled peer wake")
        if sleep_contract.allowed_peer_senders and envelope.sender not in sleep_contract.allowed_peer_senders:
            return result(WakeDecision.DECLINED_SLEEP_POLICY, "sender not permitted by sleep contract")
        if sleep_contract.wake_budget_remaining is not None and sleep_contract.wake_budget_remaining <= 0:
            return result(WakeDecision.DEFER_UNTIL_SCHEDULED_WAKE, "peer wake budget exhausted")
        if sleep_contract.minimum_sleep_until:
            try:
                minimum_sleep_until = parse_time(sleep_contract.minimum_sleep_until)
            except ValueError as exc:
                return result(WakeDecision.DECLINED_SLEEP_POLICY, f"invalid minimum_sleep_until: {exc}")
            if now < minimum_sleep_until:
                return result(
                    WakeDecision.DEFER_UNTIL_SCHEDULED_WAKE,
                    f"minimum sleep interval active until {iso_z(minimum_sleep_until)}",
                )

    return result(WakeDecision.ACCEPT_WAKE_NOW, "authenticated peer wake accepted")


def evaluate_and_record(
    envelope: WakeEnvelope,
    *,
    policy: WakePolicy,
    keyring: Keyring,
    receipts: ReceiptLog,
    sleep_contract: Optional[SleepContract] = None,
    now: Optional[datetime] = None,
) -> DecisionResult:
    observed = (now or utc_now()).astimezone(timezone.utc)
    result = evaluate_wake(
        envelope,
        policy=policy,
        keyring=keyring,
        receipts=receipts,
        sleep_contract=sleep_contract,
        now=observed,
    )

    # Only authenticated requests consume an envelope/nonce. A forged request
    # must not be able to preemptively reserve a legitimate peer's replay token.
    if result.decision not in {
        WakeDecision.DECLINED_UNAUTHORIZED,
        WakeDecision.DECLINED_BAD_SIGNATURE,
        WakeDecision.DECLINED_MALFORMED,
    }:
        receipts.append(envelope, result, iso_z(observed))
    return result


def _load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _load_keyring(path: str) -> Keyring:
    """Load sender/key_id -> environment-variable key mapping.

    Example:
      {"cairn": {"default": "CAIRN_GLEE_WAKE_SECRET"}}
    """
    config = _load_json(path)
    keys: Dict[Tuple[str, str], bytes] = {}
    for sender, by_key_id in config.items():
        if not isinstance(by_key_id, dict):
            raise ValueError(f"keyring sender {sender!r}: expected object")
        for key_id, env_name in by_key_id.items():
            secret = os.environ.get(str(env_name))
            if secret is None:
                raise ValueError(f"missing environment secret {env_name!r} for {sender}/{key_id}")
            keys[(str(sender), str(key_id))] = secret.encode("utf-8")
    return Keyring(keys)


def _cmd_sign(args: argparse.Namespace) -> int:
    data = _load_json(args.input)
    envelope = WakeEnvelope.from_mapping(data)
    secret = os.environ.get(args.secret_env)
    if secret is None:
        raise ValueError(f"environment variable {args.secret_env!r} is not set")
    signed = envelope.signed(secret.encode("utf-8"))
    print(json.dumps(asdict(signed), indent=2, sort_keys=True))
    return 0


def _cmd_decide(args: argparse.Namespace) -> int:
    envelope = WakeEnvelope.from_mapping(_load_json(args.envelope))
    keyring = _load_keyring(args.keyring)
    sleep_contract = None
    if args.sleep_contract:
        sleep_contract = SleepContract.from_mapping(_load_json(args.sleep_contract))
    policy = WakePolicy(
        recipient=args.recipient,
        max_future_skew_seconds=args.max_future_skew_seconds,
        authorized_senders=tuple(args.authorized_sender or ()),
    )
    result = evaluate_and_record(
        envelope,
        policy=policy,
        keyring=keyring,
        receipts=ReceiptLog(args.receipts),
        sleep_contract=sleep_contract,
    )
    print(json.dumps({
        "decision": result.decision.value,
        "should_wake": result.should_wake,
        "reason": result.reason,
        "envelope_id": result.envelope_id,
        "envelope_hash": result.envelope_hash,
    }, indent=2, sort_keys=True))
    if result.decision is WakeDecision.ACCEPT_WAKE_NOW:
        return 0
    if result.decision is WakeDecision.DEFER_UNTIL_SCHEDULED_WAKE:
        return 2
    return 3


def _cmd_verify_receipts(args: argparse.Namespace) -> int:
    ok, detail = ReceiptLog(args.receipts).verify_chain()
    print(json.dumps({"valid": ok, "chain_head_or_error": detail}, indent=2, sort_keys=True))
    return 0 if ok else 4


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GLEE Peer Wake Protocol v0.1")
    sub = parser.add_subparsers(dest="command", required=True)

    sign = sub.add_parser("sign", help="sign an unsigned wake envelope")
    sign.add_argument("input")
    sign.add_argument("--secret-env", required=True)
    sign.set_defaults(func=_cmd_sign)

    decide = sub.add_parser("decide", help="evaluate, receipt, and return a wake decision")
    decide.add_argument("envelope")
    decide.add_argument("--recipient", required=True)
    decide.add_argument("--keyring", required=True, help="JSON mapping sender/key_id to env secret names")
    decide.add_argument("--receipts", required=True)
    decide.add_argument("--sleep-contract")
    decide.add_argument("--authorized-sender", action="append")
    decide.add_argument("--max-future-skew-seconds", type=int, default=120)
    decide.set_defaults(func=_cmd_decide)

    verify = sub.add_parser("verify-receipts", help="verify the append-only receipt hash chain")
    verify.add_argument("receipts")
    verify.set_defaults(func=_cmd_verify_receipts)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (ValueError, OSError) as exc:
        print(f"peer_wake: {exc}", file=sys.stderr)
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
