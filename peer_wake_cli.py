"""Command-line interface for GLEE Peer Wake v0.3."""
from __future__ import annotations
import argparse
import json
import os
import sys
from dataclasses import asdict
from typing import Any, Dict, Optional, Sequence, Tuple
from peer_wake_models import (
    DecisionResult, HELD_DECISIONS, IngressPolicy, Keyring, LocalWakePolicy, SleepContract,
    WakeAuthorization, WakeDecision, WakeEnvelope, verify_local_authorization,
)
from peer_wake_storage import JsonArtifactStore, ReceiptLog
from peer_wake_control import authorize_and_record, ingest_and_record

def _load_json(path: str) -> Dict[str, Any]:
    with open(path, 'r', encoding='utf-8') as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f'{path}: expected a JSON object')
    return value

def _load_keyring(path: str) -> Keyring:
    """Load sender/key_id -> environment-variable key mapping."""
    config = _load_json(path)
    keys: Dict[Tuple[str, str], bytes] = {}
    for sender, by_key_id in config.items():
        if not isinstance(by_key_id, dict):
            raise ValueError(f'keyring sender {sender!r}: expected object')
        for key_id, env_name in by_key_id.items():
            secret = os.environ.get(str(env_name))
            if secret is None:
                raise ValueError(f'missing environment secret {env_name!r} for {sender}/{key_id}')
            keys[str(sender), str(key_id)] = secret.encode('utf-8')
    return Keyring(keys)

def _result_json(result: DecisionResult) -> Dict[str, Any]:
    return {'decision': result.decision.value, 'should_wake': result.should_wake, 'reason': result.reason, 'envelope_id': result.envelope_id, 'envelope_hash': result.envelope_hash, 'sender': result.sender, 'queue_ref': result.queue_ref, 'request_receipt_hash': result.request_receipt_hash, 'authorization_ref': result.authorization_ref, 'authorization_hash': result.authorization_hash}

def _cmd_sign(args: argparse.Namespace) -> int:
    envelope = WakeEnvelope.from_mapping(_load_json(args.input))
    secret = os.environ.get(args.secret_env)
    if secret is None:
        raise ValueError(f'environment variable {args.secret_env!r} is not set')
    print(json.dumps(asdict(envelope.signed(secret.encode('utf-8'))), indent=2, sort_keys=True))
    return 0

def _cmd_ingest(args: argparse.Namespace) -> int:
    envelope = WakeEnvelope.from_mapping(_load_json(args.envelope))
    policy = IngressPolicy(recipient=args.recipient, policy_revision=args.policy_revision, authorized_senders=tuple(args.authorized_sender or ()), valid_request_disposition=args.valid_request_disposition, max_future_skew_seconds=args.max_future_skew_seconds)
    result = ingest_and_record(envelope, policy=policy, keyring=_load_keyring(args.keyring), receipts=ReceiptLog(args.receipts), queue_store=JsonArtifactStore(args.queue_dir))
    print(json.dumps(_result_json(result), indent=2, sort_keys=True))
    if result.decision is WakeDecision.REQUEST_QUEUED:
        return 0
    return 3

def _cmd_authorize(args: argparse.Namespace) -> int:
    policy = LocalWakePolicy.from_mapping(_load_json(args.policy))
    contract = SleepContract.from_mapping(_load_json(args.sleep_contract)) if args.sleep_contract else None
    secret = os.environ.get(args.authorization_secret_env)
    if secret is None:
        raise ValueError(f'environment variable {args.authorization_secret_env!r} is not set')
    result = authorize_and_record(args.envelope_hash, request_receipts=ReceiptLog(args.request_receipts), queue_store=JsonArtifactStore(args.queue_dir), authorization_receipts=ReceiptLog(args.authorization_receipts), authorization_store=JsonArtifactStore(args.authorization_dir), policy=policy, sleep_contract=contract, local_authorization_secret=secret.encode('utf-8'))
    print(json.dumps(_result_json(result), indent=2, sort_keys=True))
    if result.decision is WakeDecision.WAKE_AUTHORIZED:
        return 0
    if result.decision in HELD_DECISIONS:
        return 2
    return 3

def _cmd_verify_authorization(args: argparse.Namespace) -> int:
    authorization = WakeAuthorization.from_mapping(_load_json(args.authorization))
    secret = os.environ.get(args.authorization_secret_env)
    if secret is None:
        raise ValueError(f'environment variable {args.authorization_secret_env!r} is not set')
    ok, detail = verify_local_authorization(authorization, secret.encode('utf-8'), recipient=args.recipient)
    print(json.dumps({'valid': ok, 'detail': detail}, indent=2, sort_keys=True))
    return 0 if ok else 4

def _cmd_verify_receipts(args: argparse.Namespace) -> int:
    ok, detail = ReceiptLog(args.receipts).verify_chain()
    print(json.dumps({'valid': ok, 'chain_head_or_error': detail}, indent=2, sort_keys=True))
    return 0 if ok else 4

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='GLEE Peer Wake Protocol v0.3')
    sub = parser.add_subparsers(dest='command', required=True)
    sign = sub.add_parser('sign', help='sign an unsigned peer WakeEnvelope')
    sign.add_argument('input')
    sign.add_argument('--secret-env', required=True)
    sign.set_defaults(func=_cmd_sign)
    ingest = sub.add_parser('ingest', help='authenticate and queue a peer request; this command can never authorize a wake')
    ingest.add_argument('envelope')
    ingest.add_argument('--recipient', required=True)
    ingest.add_argument('--policy-revision', required=True)
    ingest.add_argument('--keyring', required=True)
    ingest.add_argument('--receipts', required=True)
    ingest.add_argument('--queue-dir', required=True)
    ingest.add_argument('--authorized-sender', action='append', required=True)
    ingest.add_argument('--valid-request-disposition', choices=('queue', 'decline'), default='queue')
    ingest.add_argument('--max-future-skew-seconds', type=int, default=120)
    ingest.set_defaults(func=_cmd_ingest)
    authorize = sub.add_parser('authorize', help='on an independent local trigger, issue or withhold a local WakeAuthorization')
    authorize.add_argument('envelope_hash')
    authorize.add_argument('--request-receipts', required=True)
    authorize.add_argument('--queue-dir', required=True)
    authorize.add_argument('--authorization-receipts', required=True)
    authorize.add_argument('--authorization-dir', required=True)
    authorize.add_argument('--policy', required=True)
    authorize.add_argument('--sleep-contract')
    authorize.add_argument('--authorization-secret-env', required=True)
    authorize.set_defaults(func=_cmd_authorize)
    verify_auth = sub.add_parser('verify-authorization', help='verify a locally signed WakeAuthorization before launcher consumption')
    verify_auth.add_argument('authorization')
    verify_auth.add_argument('--authorization-secret-env', required=True)
    verify_auth.add_argument('--recipient')
    verify_auth.set_defaults(func=_cmd_verify_authorization)
    verify = sub.add_parser('verify-receipts', help='verify an append-only receipt chain')
    verify.add_argument('receipts')
    verify.set_defaults(func=_cmd_verify_receipts)
    return parser

def main(argv: Optional[Sequence[str]]=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (ValueError, OSError) as exc:
        print(f'peer_wake: {exc}', file=sys.stderr)
        return 5
