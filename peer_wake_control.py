"""Two-stage queue and local authorization control plane for Peer Wake v0.3."""
from __future__ import annotations
from dataclasses import asdict
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from peer_wake_models import (
    AUTHORIZATION_PROTOCOL, PROTOCOL, ComputeLease, DecisionResult, IngressPolicy,
    Keyring, LocalWakePolicy, SleepContract, WakeAuthorization, WakeDecision,
    WakeEnvelope, _base_result, iso_z, parse_time, sha256_json, utc_now,
    validate_compute_lease, validate_local_policy, validate_sleep_contract,
    verify_peer_signature,
)
from peer_wake_storage import JsonArtifactStore, ReceiptLog

def evaluate_ingress(envelope: WakeEnvelope, *, policy: IngressPolicy, keyring: Keyring, receipts: ReceiptLog, now: Optional[datetime]=None) -> DecisionResult:
    """Evaluate a peer request. This function can never authorize a wake."""
    policy.validate()
    observed = (now or utc_now()).astimezone(timezone.utc)
    string_fields = {'protocol': envelope.protocol, 'envelope_id': envelope.envelope_id, 'sender': envelope.sender, 'recipient': envelope.recipient, 'issued_at': envelope.issued_at, 'expires_at': envelope.expires_at, 'nonce': envelope.nonce, 'reason': envelope.reason, 'task': envelope.task, 'key_id': envelope.key_id, 'signature_alg': envelope.signature_alg, 'signature': envelope.signature}
    if any((not isinstance(value, str) for value in string_fields.values())):
        return _base_result(envelope, WakeDecision.DECLINED_MALFORMED, 'identity/content fields must be strings')
    if envelope.protocol != PROTOCOL:
        return _base_result(envelope, WakeDecision.DECLINED_MALFORMED, f'unsupported protocol={envelope.protocol}')
    if not envelope.envelope_id or not envelope.nonce or (not envelope.sender):
        return _base_result(envelope, WakeDecision.DECLINED_MALFORMED, 'identity/replay fields must be non-empty')
    if not envelope.reason.strip() or not envelope.task.strip():
        return _base_result(envelope, WakeDecision.DECLINED_MALFORMED, 'reason and task must be non-empty')
    if isinstance(envelope.priority, bool) or not isinstance(envelope.priority, int):
        return _base_result(envelope, WakeDecision.DECLINED_MALFORMED, 'priority must be an integer')
    if not 0 <= envelope.priority <= 100:
        return _base_result(envelope, WakeDecision.DECLINED_MALFORMED, 'priority must be between 0 and 100')
    if envelope.sender not in policy.authorized_senders:
        return _base_result(envelope, WakeDecision.DECLINED_UNAUTHORIZED, 'sender not authorized by local ingress policy')
    signature_ok, signature_reason = verify_peer_signature(envelope, keyring)
    if not signature_ok:
        decision = WakeDecision.DECLINED_UNAUTHORIZED if 'no trusted key' in signature_reason else WakeDecision.DECLINED_BAD_SIGNATURE
        return _base_result(envelope, decision, signature_reason)
    if envelope.recipient != policy.recipient:
        return _base_result(envelope, WakeDecision.DECLINED_WRONG_RECIPIENT, f'expected recipient={policy.recipient}')
    try:
        issued_at = parse_time(envelope.issued_at)
        expires_at = parse_time(envelope.expires_at)
    except ValueError as exc:
        return _base_result(envelope, WakeDecision.DECLINED_MALFORMED, f'invalid timestamp: {exc}')
    if expires_at <= issued_at:
        return _base_result(envelope, WakeDecision.DECLINED_MALFORMED, 'expires_at must be after issued_at')
    if (issued_at - observed).total_seconds() > policy.max_future_skew_seconds:
        return _base_result(envelope, WakeDecision.DECLINED_FUTURE_ISSUE, 'issued_at is too far in the future')
    if observed >= expires_at:
        return _base_result(envelope, WakeDecision.DECLINED_EXPIRED, 'wake envelope expired')
    if receipts.consumed(envelope):
        return _base_result(envelope, WakeDecision.DECLINED_REPLAY, 'envelope_id or sender nonce already consumed')
    if policy.valid_request_disposition == 'decline':
        return _base_result(envelope, WakeDecision.DECLINED_LOCAL_POLICY, 'perfectly valid request declined by local ingress policy')
    return _base_result(envelope, WakeDecision.REQUEST_QUEUED, 'authenticated peer request queued; no wake authority granted')

def ingest_and_record(envelope: WakeEnvelope, *, policy: IngressPolicy, keyring: Keyring, receipts: ReceiptLog, queue_store: JsonArtifactStore, now: Optional[datetime]=None) -> DecisionResult:
    observed = (now or utc_now()).astimezone(timezone.utc)
    with receipts.exclusive_lock():
        result = evaluate_ingress(envelope, policy=policy, keyring=keyring, receipts=receipts, now=observed)
        authenticated = result.decision not in {WakeDecision.DECLINED_UNAUTHORIZED, WakeDecision.DECLINED_BAD_SIGNATURE, WakeDecision.DECLINED_MALFORMED}
        if not authenticated:
            return result
        queue_ref = ''
        if result.decision is WakeDecision.REQUEST_QUEUED:
            queue_ref = queue_store.store(asdict(envelope))
        record = receipts._append_unlocked({'record_type': 'peer_request', 'protocol': PROTOCOL, 'observed_at': iso_z(observed), 'envelope_id': envelope.envelope_id, 'envelope_hash': envelope.envelope_hash(), 'sender': envelope.sender, 'recipient': envelope.recipient, 'nonce': envelope.nonce, 'peer_claimed_priority': envelope.priority, 'decision': result.decision.value, 'reason': result.reason, 'queue_ref': queue_ref, 'ingress_policy_revision': policy.policy_revision, 'ingress_policy_hash': sha256_json(asdict(policy))})
        return DecisionResult(**{**asdict(result), 'queue_ref': queue_ref, 'request_receipt_hash': record['receipt_hash']})

def _authorization_record(*, observed: datetime, decision: WakeDecision, reason: str, envelope_hash: str, queued_record: Optional[Mapping[str, Any]], policy: LocalWakePolicy, authorization_ref: str='', authorization_hash: str='', lease: Optional[ComputeLease]=None) -> Dict[str, Any]:
    return {'record_type': 'local_authorization_decision', 'protocol': AUTHORIZATION_PROTOCOL, 'observed_at': iso_z(observed), 'envelope_id': str(queued_record.get('envelope_id', '')) if queued_record else '', 'envelope_hash': envelope_hash, 'sender': str(queued_record.get('sender', '')) if queued_record else '', 'request_receipt_hash': str(queued_record.get('receipt_hash', '')) if queued_record else '', 'decision': decision.value, 'reason': reason, 'local_policy_revision': policy.policy_revision, 'local_policy_hash': sha256_json(asdict(policy)), 'authorization_ref': authorization_ref, 'authorization_hash': authorization_hash, 'compute_lease': asdict(lease) if lease is not None else {}}

def authorize_and_record(envelope_hash: str, *, request_receipts: ReceiptLog, queue_store: JsonArtifactStore, authorization_receipts: ReceiptLog, authorization_store: JsonArtifactStore, policy: LocalWakePolicy, sleep_contract: Optional[SleepContract], local_authorization_secret: bytes, now: Optional[datetime]=None) -> DecisionResult:
    """Issue a local wake capability on an independent local trigger.

    The function takes an envelope hash, not a peer message callback. Local
    policy, stop state, sleep state, and lease are loaded independently.
    """
    validate_local_policy(policy)
    observed = (now or utc_now()).astimezone(timezone.utc)
    ok, detail = request_receipts.verify_chain()
    if not ok:
        raise ValueError(f'invalid request receipt chain: {detail}')
    queued_record = request_receipts.find_queued(envelope_hash)
    with authorization_receipts.exclusive_lock():
        ok, detail = authorization_receipts.verify_chain()
        if not ok:
            raise ValueError(f'invalid authorization receipt chain: {detail}')
        if queued_record is None:
            result = DecisionResult(WakeDecision.DECLINED_REQUEST_NOT_QUEUED, 'no authenticated queued request matches envelope_hash', envelope_hash=envelope_hash)
            authorization_receipts._append_unlocked(_authorization_record(observed=observed, decision=result.decision, reason=result.reason, envelope_hash=envelope_hash, queued_record=None, policy=policy))
            return result
        base = {'envelope_id': str(queued_record['envelope_id']), 'envelope_hash': envelope_hash, 'sender': str(queued_record['sender']), 'request_receipt_hash': str(queued_record['receipt_hash'])}
        if authorization_receipts.already_authorized(envelope_hash):
            result = DecisionResult(WakeDecision.DECLINED_REPLAY, 'request already has a local wake authorization', **base)
            authorization_receipts._append_unlocked(_authorization_record(observed=observed, decision=result.decision, reason=result.reason, envelope_hash=envelope_hash, queued_record=queued_record, policy=policy))
            return result
        if Path(policy.stop_marker_path).exists():
            result = DecisionResult(WakeDecision.HELD_OPERATOR_STOP, 'operator stop marker outranks peer request and local policy', **base)
            authorization_receipts._append_unlocked(_authorization_record(observed=observed, decision=result.decision, reason=result.reason, envelope_hash=envelope_hash, queued_record=queued_record, policy=policy))
            return result
        if policy.mode == 'queue_only':
            result = DecisionResult(WakeDecision.HELD_QUEUE_ONLY, 'local policy is queue-only; request remains evidence for an ordinary wake', **base)
            authorization_receipts._append_unlocked(_authorization_record(observed=observed, decision=result.decision, reason=result.reason, envelope_hash=envelope_hash, queued_record=queued_record, policy=policy))
            return result
        if policy.mode == 'decline':
            result = DecisionResult(WakeDecision.DECLINED_LOCAL_POLICY, 'perfectly valid queued request declined by local policy', **base)
            authorization_receipts._append_unlocked(_authorization_record(observed=observed, decision=result.decision, reason=result.reason, envelope_hash=envelope_hash, queued_record=queued_record, policy=policy))
            return result
        queue_ref = str(queued_record.get('queue_ref', ''))
        if not queue_ref:
            raise ValueError('queued request receipt has no queue_ref')
        envelope = WakeEnvelope.from_mapping(queue_store.load(queue_ref))
        if envelope.envelope_hash() != envelope_hash:
            raise ValueError('queued envelope hash does not match request receipt')
        if envelope.sender not in policy.authorized_senders:
            result = DecisionResult(WakeDecision.DECLINED_LOCAL_POLICY, 'sender not authorized by local wake policy', **base)
            authorization_receipts._append_unlocked(_authorization_record(observed=observed, decision=result.decision, reason=result.reason, envelope_hash=envelope_hash, queued_record=queued_record, policy=policy))
            return result
        if sleep_contract is None:
            result = DecisionResult(WakeDecision.HELD_NO_SLEEP_CONTRACT, 'immediate authorization fails closed without a SleepContract', **base)
            authorization_receipts._append_unlocked(_authorization_record(observed=observed, decision=result.decision, reason=result.reason, envelope_hash=envelope_hash, queued_record=queued_record, policy=policy))
            return result
        validate_sleep_contract(sleep_contract)
        if sleep_contract.agent_id != policy.recipient:
            result = DecisionResult(WakeDecision.DECLINED_SLEEP_POLICY, 'sleep contract belongs to another agent', **base)
            authorization_receipts._append_unlocked(_authorization_record(observed=observed, decision=result.decision, reason=result.reason, envelope_hash=envelope_hash, queued_record=queued_record, policy=policy))
            return result
        if sleep_contract.stop_policy_revision != policy.stop_policy_revision:
            result = DecisionResult(WakeDecision.DECLINED_SLEEP_POLICY, 'sleep contract stop-policy revision does not match local policy', **base)
            authorization_receipts._append_unlocked(_authorization_record(observed=observed, decision=result.decision, reason=result.reason, envelope_hash=envelope_hash, queued_record=queued_record, policy=policy))
            return result
        if sleep_contract.minimum_sleep_until:
            minimum = parse_time(sleep_contract.minimum_sleep_until)
            if observed < minimum:
                result = DecisionResult(WakeDecision.HELD_MINIMUM_SLEEP, f'minimum sleep interval active until {iso_z(minimum)}', **base)
                authorization_receipts._append_unlocked(_authorization_record(observed=observed, decision=result.decision, reason=result.reason, envelope_hash=envelope_hash, queued_record=queued_record, policy=policy))
                return result
        issued_at = iso_z(observed)
        expires_at = iso_z(observed + timedelta(seconds=policy.authorization_ttl_seconds))
        authorization = WakeAuthorization(protocol=AUTHORIZATION_PROTOCOL, authorization_id=str(uuid.uuid4()), issued_at=issued_at, expires_at=expires_at, recipient=policy.recipient, sender=envelope.sender, envelope_id=envelope.envelope_id, envelope_hash=envelope_hash, request_receipt_hash=str(queued_record['receipt_hash']), sleep_id=sleep_contract.sleep_id, local_policy_revision=policy.policy_revision, local_policy_hash=sha256_json(asdict(policy)), rules_revision=sleep_contract.rules_revision, declared_model_id=sleep_contract.model_id, compute_lease=asdict(policy.compute_lease)).signed(local_authorization_secret)
        authorization_value = asdict(authorization)
        authorization_ref = authorization_store.store(authorization_value)
        authorization_hash = authorization.authorization_hash()
        result = DecisionResult(WakeDecision.WAKE_AUTHORIZED, 'local wake authorization issued with a bounded compute lease', authorization_ref=authorization_ref, authorization_hash=authorization_hash, **base)
        authorization_receipts._append_unlocked(_authorization_record(observed=observed, decision=result.decision, reason=result.reason, envelope_hash=envelope_hash, queued_record=queued_record, policy=policy, authorization_ref=authorization_ref, authorization_hash=authorization_hash, lease=policy.compute_lease))
        return result
