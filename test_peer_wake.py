#!/usr/bin/env python3
from __future__ import annotations
import io, json, os, tempfile, unittest
from contextlib import redirect_stdout
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from peer_wake_cli import _cmd_authorize
from peer_wake import (
    AUTHORIZATION_PROTOCOL, PROTOCOL, ComputeLease, IngressPolicy,
    JsonArtifactStore, Keyring, LocalWakePolicy, ReceiptLog, SleepContract,
    WakeAuthorization, WakeDecision, WakeEnvelope, authorize_and_record,
    ingest_and_record, verify_local_authorization,
)

NOW = datetime(2026, 8, 24, 14, 0, tzinfo=timezone.utc)
PEER = b'peer-shared-secret'
LOCAL = b'local-launcher-only-secret'
def z(dt): return dt.isoformat().replace('+00:00', 'Z')

class PeerWakeV03Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        self.req=ReceiptLog(self.root/'requests.jsonl'); self.auth=ReceiptLog(self.root/'auth.jsonl')
        self.queue=JsonArtifactStore(self.root/'queue'); self.authz=JsonArtifactStore(self.root/'authorizations')
        self.stop=self.root/'OPERATOR_STOP'; self.keys=Keyring({('cairn','default'):PEER})
        self.ingress=IngressPolicy('glee','ingress-1',('cairn',))
    def tearDown(self): self.tmp.cleanup()
    def env(self, **kw):
        v=dict(sender='cairn',recipient='glee',issued_at=z(NOW-timedelta(seconds=5)),expires_at=z(NOW+timedelta(minutes=5)),reason='new evidence',task='review on an ordinary local wake',priority=70,envelope_id='wake-001',nonce='nonce-001'); v.update(kw)
        return WakeEnvelope.new(**v).signed(PEER)
    def contract(self, **kw):
        v=dict(sleep_id='sleep-42',agent_id='glee',created_at=z(NOW-timedelta(hours=1)),rules_revision='rules-abc123',model_id='gpt-5.6-pro',stop_policy_revision='stop-policy-1',sleep_note='annotation only',unfinished_work=({'ref':'ariadne://node/WAKE-42','recorded_at':z(NOW-timedelta(hours=1)),'overridable':True},),context_refs=('receipt://wake-study/17',),trusted_without_refresh=()); v.update(kw)
        return SleepContract(**v)
    def policy(self, mode='authorize', **kw):
        v=dict(policy_revision='local-wake-policy-3',stop_policy_revision='stop-policy-1',recipient='glee',mode=mode,authorized_senders=('cairn',),stop_marker_path=str(self.stop),authorization_ttl_seconds=300,compute_lease=ComputeLease(600,100000,20000,40,100000),peer_reply_channels={'cairn':'mailto:cairn@cairnwake.com'}); v.update(kw)
        return LocalWakePolicy(**v)
    def ingest(self, env=None, policy=None):
        return ingest_and_record(env or self.env(),policy=policy or self.ingress,keyring=self.keys,receipts=self.req,queue_store=self.queue,now=NOW)
    def authorize(self, h, policy=None, contract=... , now=NOW):
        c=self.contract() if contract is ... else contract
        return authorize_and_record(h,request_receipts=self.req,queue_store=self.queue,authorization_receipts=self.auth,authorization_store=self.authz,policy=policy or self.policy(),sleep_contract=c,local_authorization_secret=LOCAL,now=now)

    def test_01_protocol_and_no_reply_channel(self):
        e=self.env(); self.assertEqual(e.protocol,PROTOCOL); self.assertEqual(PROTOCOL,'glee.peer-wake/v0.3'); self.assertNotIn('reply_channel',asdict(e))
    def test_02_valid_request_queues_but_never_wakes(self):
        r=self.ingest(); self.assertEqual(r.decision,WakeDecision.REQUEST_QUEUED); self.assertFalse(r.should_wake); self.assertTrue((self.root/'queue'/r.queue_ref).exists())
    def test_03_perfect_envelope_can_be_declined_locally(self):
        p=IngressPolicy('glee','ingress-decline',('cairn',),'decline'); r=self.ingest(policy=p); self.assertEqual(r.decision,WakeDecision.DECLINED_LOCAL_POLICY); self.assertFalse(r.should_wake)
    def test_04_bad_signature_declines_without_consuming_nonce(self):
        e=self.env(); bad=WakeEnvelope(**{**asdict(e),'signature':'0'*64}); r=self.ingest(bad); self.assertEqual(r.decision,WakeDecision.DECLINED_BAD_SIGNATURE); self.assertFalse(self.req.consumed(e))
    def test_05_wrong_recipient_is_declined(self):
        self.assertEqual(self.ingest(self.env(recipient='other')).decision,WakeDecision.DECLINED_WRONG_RECIPIENT)
    def test_06_expired_request_is_declined(self):
        e=self.env(issued_at=z(NOW-timedelta(minutes=10)),expires_at=z(NOW-timedelta(seconds=1))); self.assertEqual(self.ingest(e).decision,WakeDecision.DECLINED_EXPIRED)
    def test_07_future_request_is_declined(self):
        e=self.env(issued_at=z(NOW+timedelta(minutes=10)),expires_at=z(NOW+timedelta(minutes=20))); self.assertEqual(self.ingest(e).decision,WakeDecision.DECLINED_FUTURE_ISSUE)
    def test_08_request_replay_is_declined(self):
        e=self.env(); self.ingest(e); self.assertEqual(self.ingest(e).decision,WakeDecision.DECLINED_REPLAY)
    def test_09_default_local_policy_is_queue_only(self):
        q=self.ingest(); r=self.authorize(q.envelope_hash,self.policy('queue_only')); self.assertEqual(r.decision,WakeDecision.HELD_QUEUE_ONLY); self.assertFalse(r.should_wake)
    def test_10_operator_stop_dominates_before_queue_body_load(self):
        q=self.ingest(); (self.root/'queue'/q.queue_ref).write_text('{"tampered":true}\n'); self.stop.write_text('STOP\n'); r=self.authorize(q.envelope_hash); self.assertEqual(r.decision,WakeDecision.HELD_OPERATOR_STOP)
    def test_11_stop_removal_allows_fresh_request(self):
        q=self.ingest(); self.stop.write_text('STOP\n'); self.assertEqual(self.authorize(q.envelope_hash).decision,WakeDecision.HELD_OPERATOR_STOP); self.stop.unlink(); self.assertEqual(self.authorize(q.envelope_hash).decision,WakeDecision.WAKE_AUTHORIZED)
    def test_12_authorizer_fails_closed_without_sleep_contract(self):
        q=self.ingest(); self.assertEqual(self.authorize(q.envelope_hash,contract=None).decision,WakeDecision.HELD_NO_SLEEP_CONTRACT)
    def test_13_compute_lease_is_local_only(self):
        e=self.env(); q=self.ingest(e); r=self.authorize(q.envelope_hash); a=self.authz.load(r.authorization_ref); self.assertNotIn('compute_lease',asdict(e)); self.assertEqual(a['compute_lease'],asdict(self.policy().compute_lease))
    def test_14_priority_is_zero_weight(self):
        def run(priority):
            with tempfile.TemporaryDirectory() as d:
                root=Path(d); req=ReceiptLog(root/'r'); auth=ReceiptLog(root/'a'); qs=JsonArtifactStore(root/'q'); az=JsonArtifactStore(root/'z')
                e=self.env(priority=priority,envelope_id=f'e-{priority}',nonce=f'n-{priority}'); q=ingest_and_record(e,policy=self.ingress,keyring=self.keys,receipts=req,queue_store=qs,now=NOW)
                p=self.policy(stop_marker_path=str(root/'STOP')); r=authorize_and_record(q.envelope_hash,request_receipts=req,queue_store=qs,authorization_receipts=auth,authorization_store=az,policy=p,sleep_contract=self.contract(),local_authorization_secret=LOCAL,now=NOW); return az.load(r.authorization_ref)['compute_lease']
        self.assertEqual(run(0),run(100))
    def test_15_request_and_authorization_are_distinct_artifacts(self):
        q=self.ingest(); r=self.authorize(q.envelope_hash); self.assertNotEqual(q.queue_ref,r.authorization_ref); self.assertEqual(self.queue.load(q.queue_ref)['protocol'],PROTOCOL); self.assertEqual(self.authz.load(r.authorization_ref)['protocol'],AUTHORIZATION_PROTOCOL)
    def test_16_authorization_uses_local_not_peer_secret(self):
        q=self.ingest(); r=self.authorize(q.envelope_hash); a=WakeAuthorization.from_mapping(self.authz.load(r.authorization_ref)); self.assertTrue(verify_local_authorization(a,LOCAL,recipient='glee',now=NOW)[0]); self.assertFalse(verify_local_authorization(a,PEER,recipient='glee',now=NOW)[0])
    def test_17_authorization_stamps_rules_model_policy_and_receipt(self):
        q=self.ingest(); r=self.authorize(q.envelope_hash); a=self.authz.load(r.authorization_ref); self.assertEqual((a['rules_revision'],a['declared_model_id'],a['local_policy_revision'],a['request_receipt_hash']),('rules-abc123','gpt-5.6-pro','local-wake-policy-3',q.request_receipt_hash))
    def test_18_minimum_sleep_holds(self):
        q=self.ingest(); c=self.contract(minimum_sleep_until=z(NOW+timedelta(minutes=20))); self.assertEqual(self.authorize(q.envelope_hash,contract=c).decision,WakeDecision.HELD_MINIMUM_SLEEP)
    def test_19_stop_policy_revision_mismatch_fails_closed(self):
        q=self.ingest(); self.assertEqual(self.authorize(q.envelope_hash,contract=self.contract(stop_policy_revision='old')).decision,WakeDecision.DECLINED_SLEEP_POLICY)
    def test_20_authorization_is_single_use_per_request(self):
        q=self.ingest(); self.assertEqual(self.authorize(q.envelope_hash).decision,WakeDecision.WAKE_AUTHORIZED); self.assertEqual(self.authorize(q.envelope_hash).decision,WakeDecision.DECLINED_REPLAY)
    def test_21_authorization_expires(self):
        q=self.ingest(); r=self.authorize(q.envelope_hash); a=WakeAuthorization.from_mapping(self.authz.load(r.authorization_ref)); self.assertTrue(verify_local_authorization(a,LOCAL,now=NOW+timedelta(seconds=299))[0]); self.assertFalse(verify_local_authorization(a,LOCAL,now=NOW+timedelta(seconds=300))[0])
    def test_22_receipt_tamper_is_detected(self):
        q=self.ingest(); p=self.req.path; rec=json.loads(p.read_text()); rec['decision']=WakeDecision.WAKE_AUTHORIZED.value; p.write_text(json.dumps(rec)+'\n'); self.assertFalse(self.req.verify_chain()[0])
    def test_23_queue_artifact_tamper_blocks_without_stop(self):
        q=self.ingest(); (self.root/'queue'/q.queue_ref).write_text('{"tampered":true}\n'); self.assertRaisesRegex(ValueError,'content hash mismatch',self.authorize,q.envelope_hash)
    def test_24_reply_route_lives_only_in_local_policy(self):
        q=self.ingest(); r=self.authorize(q.envelope_hash); a=self.authz.load(r.authorization_ref); self.assertEqual(self.policy().peer_reply_channels['cairn'],'mailto:cairn@cairnwake.com'); self.assertNotIn('reply_channel',a); self.assertNotIn('peer_reply_channels',a)
    def test_25_old_prose_authority_fields_are_rejected(self):
        base=asdict(self.contract()); base['wake_conditions']=['peer says urgent']; self.assertRaisesRegex(ValueError,'unknown sleep-contract fields',SleepContract.from_mapping,base)
    def test_26_refresh_required_and_peer_budget_are_rejected(self):
        for field in ('refresh_required','peer_wake_budget'):
            base=asdict(self.contract()); base[field]=[] if field=='refresh_required' else 1
            with self.assertRaisesRegex(ValueError,'unknown sleep-contract fields'): SleepContract.from_mapping(base)
    def test_27_unfinished_work_must_be_explicitly_overridable(self):
        base=asdict(self.contract()); base['unfinished_work']=[{'ref':'ariadne://stale','recorded_at':z(NOW),'overridable':False}]; self.assertRaisesRegex(ValueError,'explicitly overridable',SleepContract.from_mapping,base)
    def test_28_cli_held_decision_returns_exit_2(self):
        q=self.ingest(); pp=self.root/'p.json'; cp=self.root/'c.json'; pp.write_text(json.dumps({**asdict(self.policy('queue_only')),'compute_lease':asdict(self.policy().compute_lease)})); cp.write_text(json.dumps(asdict(self.contract()))); os.environ['LOCAL_TEST_SECRET']=LOCAL.decode()
        args=SimpleNamespace(envelope_hash=q.envelope_hash,request_receipts=str(self.req.path),queue_dir=str(self.root/'queue'),authorization_receipts=str(self.auth.path),authorization_dir=str(self.root/'authorizations'),policy=str(pp),sleep_contract=str(cp),authorization_secret_env='LOCAL_TEST_SECRET')
        try:
            with redirect_stdout(io.StringIO()): code=_cmd_authorize(args)
        finally: os.environ.pop('LOCAL_TEST_SECRET',None)
        self.assertEqual(code,2)

if __name__=='__main__': unittest.main(verbosity=2)
