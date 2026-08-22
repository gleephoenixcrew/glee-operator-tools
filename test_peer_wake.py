#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from peer_wake import (
    PROTOCOL,
    Keyring,
    ReceiptLog,
    SleepContract,
    WakeDecision,
    WakeEnvelope,
    WakePolicy,
    evaluate_and_record,
    evaluate_wake,
)


NOW = datetime(2026, 8, 22, 20, 30, tzinfo=timezone.utc)
SECRET = b"test-shared-secret"


def z(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


class PeerWakeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.receipts = ReceiptLog(Path(self.tmp.name) / "wake_receipts.jsonl")
        self.keyring = Keyring({("cairn", "default"): SECRET})
        self.policy = WakePolicy(recipient="glee", authorized_senders=("cairn",))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def envelope(self, **overrides) -> WakeEnvelope:
        values = dict(
            sender="cairn",
            recipient="glee",
            issued_at=z(NOW - timedelta(seconds=5)),
            expires_at=z(NOW + timedelta(minutes=5)),
            reason="Peer collaboration requires GLEE continuity analysis",
            task="Review Cairn wake/sleep protocol and reply with evidence",
            reply_channel="aicq:@cairn",
            priority=70,
            envelope_id="wake-001",
            nonce="nonce-001",
        )
        values.update(overrides)
        return WakeEnvelope.new(**values).signed(SECRET)

    def test_valid_authenticated_request_wakes_and_receipts(self):
        env = self.envelope()
        result = evaluate_and_record(
            env,
            policy=self.policy,
            keyring=self.keyring,
            receipts=self.receipts,
            now=NOW,
        )
        self.assertEqual(result.decision, WakeDecision.ACCEPT_WAKE_NOW)
        self.assertTrue(result.should_wake)
        ok, head = self.receipts.verify_chain()
        self.assertTrue(ok)
        self.assertEqual(len(head), 64)

    def test_bad_signature_cannot_consume_nonce(self):
        env = self.envelope()
        damaged = WakeEnvelope(**{**asdict(env), "signature": "0" * 64})
        result = evaluate_and_record(
            damaged,
            policy=self.policy,
            keyring=self.keyring,
            receipts=self.receipts,
            now=NOW,
        )
        self.assertEqual(result.decision, WakeDecision.DECLINED_BAD_SIGNATURE)
        self.assertFalse(self.receipts.consumed(env))

    def test_replay_is_declined_after_first_authenticated_decision(self):
        env = self.envelope()
        first = evaluate_and_record(
            env, policy=self.policy, keyring=self.keyring, receipts=self.receipts, now=NOW
        )
        second = evaluate_wake(
            env,
            policy=self.policy,
            keyring=self.keyring,
            receipts=self.receipts,
            now=NOW + timedelta(seconds=1),
        )
        self.assertEqual(first.decision, WakeDecision.ACCEPT_WAKE_NOW)
        self.assertEqual(second.decision, WakeDecision.DECLINED_REPLAY)

    def test_reused_sender_nonce_is_replay_even_with_new_envelope_id(self):
        first = self.envelope()
        evaluate_and_record(
            first, policy=self.policy, keyring=self.keyring, receipts=self.receipts, now=NOW
        )
        second = self.envelope(envelope_id="wake-002", nonce="nonce-001")
        result = evaluate_wake(
            second,
            policy=self.policy,
            keyring=self.keyring,
            receipts=self.receipts,
            now=NOW,
        )
        self.assertEqual(result.decision, WakeDecision.DECLINED_REPLAY)

    def test_expired_envelope_is_declined(self):
        env = self.envelope(
            issued_at=z(NOW - timedelta(minutes=10)),
            expires_at=z(NOW - timedelta(seconds=1)),
        )
        result = evaluate_wake(
            env, policy=self.policy, keyring=self.keyring, receipts=self.receipts, now=NOW
        )
        self.assertEqual(result.decision, WakeDecision.DECLINED_EXPIRED)

    def test_future_issue_beyond_clock_skew_is_declined(self):
        env = self.envelope(
            issued_at=z(NOW + timedelta(minutes=10)),
            expires_at=z(NOW + timedelta(minutes=20)),
        )
        result = evaluate_wake(
            env, policy=self.policy, keyring=self.keyring, receipts=self.receipts, now=NOW
        )
        self.assertEqual(result.decision, WakeDecision.DECLINED_FUTURE_ISSUE)

    def test_wrong_recipient_is_declined(self):
        env = self.envelope(recipient="some-other-agent")
        result = evaluate_wake(
            env, policy=self.policy, keyring=self.keyring, receipts=self.receipts, now=NOW
        )
        self.assertEqual(result.decision, WakeDecision.DECLINED_WRONG_RECIPIENT)

    def test_sleep_contract_can_disable_peer_wake(self):
        env = self.envelope()
        contract = SleepContract(
            sleep_id="sleep-001",
            agent_id="glee",
            created_at=z(NOW - timedelta(hours=1)),
            reason_for_sleep="no safe useful work",
            peer_wake_enabled=False,
        )
        result = evaluate_wake(
            env,
            policy=self.policy,
            keyring=self.keyring,
            receipts=self.receipts,
            sleep_contract=contract,
            now=NOW,
        )
        self.assertEqual(result.decision, WakeDecision.DECLINED_PEER_WAKE_DISABLED)

    def test_minimum_sleep_period_defers_without_waking(self):
        env = self.envelope()
        contract = SleepContract(
            sleep_id="sleep-002",
            agent_id="glee",
            created_at=z(NOW - timedelta(minutes=1)),
            reason_for_sleep="cooldown",
            minimum_sleep_until=z(NOW + timedelta(minutes=20)),
            allowed_peer_senders=("cairn",),
        )
        result = evaluate_and_record(
            env,
            policy=self.policy,
            keyring=self.keyring,
            receipts=self.receipts,
            sleep_contract=contract,
            now=NOW,
        )
        self.assertEqual(result.decision, WakeDecision.DEFER_UNTIL_SCHEDULED_WAKE)
        self.assertTrue(self.receipts.consumed(env))

    def test_exhausted_peer_wake_budget_defers(self):
        env = self.envelope()
        contract = SleepContract(
            sleep_id="sleep-003",
            agent_id="glee",
            created_at=z(NOW - timedelta(hours=1)),
            reason_for_sleep="budget protection",
            wake_budget_remaining=0,
        )
        result = evaluate_wake(
            env,
            policy=self.policy,
            keyring=self.keyring,
            receipts=self.receipts,
            sleep_contract=contract,
            now=NOW,
        )
        self.assertEqual(result.decision, WakeDecision.DEFER_UNTIL_SCHEDULED_WAKE)

    def test_sleep_contract_sender_allowlist_is_separate_gate(self):
        env = self.envelope()
        contract = SleepContract(
            sleep_id="sleep-004",
            agent_id="glee",
            created_at=z(NOW),
            reason_for_sleep="waiting",
            allowed_peer_senders=("zoro",),
        )
        result = evaluate_wake(
            env,
            policy=self.policy,
            keyring=self.keyring,
            receipts=self.receipts,
            sleep_contract=contract,
            now=NOW,
        )
        self.assertEqual(result.decision, WakeDecision.DECLINED_SLEEP_POLICY)

    def test_transport_metadata_does_not_change_signature_semantics(self):
        env = self.envelope(reply_channel="exuvia:agent/cairn")
        self.assertEqual(env.protocol, PROTOCOL)
        result = evaluate_wake(
            env, policy=self.policy, keyring=self.keyring, receipts=self.receipts, now=NOW
        )
        self.assertEqual(result.decision, WakeDecision.ACCEPT_WAKE_NOW)

    def test_receipt_chain_detects_tampering(self):
        env = self.envelope()
        evaluate_and_record(
            env, policy=self.policy, keyring=self.keyring, receipts=self.receipts, now=NOW
        )
        path = Path(self.tmp.name) / "wake_receipts.jsonl"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["decision"] = WakeDecision.DECLINED_SLEEP_POLICY.value
        path.write_text(json.dumps(record) + "\n", encoding="utf-8")
        ok, detail = self.receipts.verify_chain()
        self.assertFalse(ok)
        self.assertIn("receipt_hash mismatch", detail)

    def test_unknown_envelope_fields_fail_closed(self):
        data = asdict(self.envelope())
        data["please_wake_anyway"] = True
        with self.assertRaisesRegex(ValueError, "unknown fields"):
            WakeEnvelope.from_mapping(data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
