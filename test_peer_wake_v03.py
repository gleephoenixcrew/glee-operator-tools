#!/usr/bin/env python3
from __future__ import annotations

import json
import multiprocessing
import tempfile
import unittest
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from peer_wake_v03 import (
    PROTOCOL,
    AuthorizationLog,
    ComputeLease,
    Keyring,
    LocalWakePolicy,
    RequestReceiptLog,
    SleepContract,
    WakeDecision,
    WakeEnvelope,
    evaluate_and_record,
    evaluate_wake,
)

NOW = datetime(2026, 8, 24, 14, 0, tzinfo=timezone.utc)
SECRET = b"test-shared-secret"


def z(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def concurrent_attempt(request_path: str, auth_path: str, start, output) -> None:
    envelope = WakeEnvelope.new(
        sender="cairn",
        recipient="glee",
        issued_at=z(NOW - timedelta(seconds=5)),
        expires_at=z(NOW + timedelta(minutes=5)),
        reason="same concurrent request",
        task="authorize at most once",
        envelope_id="concurrent-001",
        nonce="concurrent-nonce-001",
    ).signed(SECRET)
    contract = SleepContract(
        sleep_id="sleep-concurrent",
        agent_id="glee",
        created_at=z(NOW - timedelta(hours=1)),
        rules_revision="rules@1",
        model_id="model@1",
        allowed_peer_senders=("cairn",),
    )
    start.wait()
    result = evaluate_and_record(
        envelope,
        policy=LocalWakePolicy(
            recipient="glee",
            authorized_senders=("cairn",),
            immediate_wake_enabled=True,
            compute_lease=ComputeLease(60, 4000, 5),
            policy_id="concurrency-test",
        ),
        keyring=Keyring({("cairn", "default"): SECRET}),
        request_receipts=RequestReceiptLog(request_path),
        authorizations=AuthorizationLog(auth_path),
        sleep_contract=contract,
        now=NOW,
    )
    output.put(result.decision.value)


class PeerWakeV03Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.request_path = root / "requests.jsonl"
        self.auth_path = root / "authorizations.jsonl"
        self.requests = RequestReceiptLog(self.request_path)
        self.authorizations = AuthorizationLog(self.auth_path)
        self.keyring = Keyring({("cairn", "default"): SECRET})
        self.policy = LocalWakePolicy(
            recipient="glee", authorized_senders=("cairn",)
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def envelope(self, **overrides) -> WakeEnvelope:
        values = dict(
            sender="cairn",
            recipient="glee",
            issued_at=z(NOW - timedelta(seconds=5)),
            expires_at=z(NOW + timedelta(minutes=5)),
            reason="Cairn has published new evidence",
            task="Adjudicate the public record",
            envelope_id="wake-001",
            nonce="nonce-001",
        )
        values.update(overrides)
        return WakeEnvelope.new(**values).signed(SECRET)

    def contract(self, **overrides) -> SleepContract:
        values = dict(
            sleep_id="sleep-154",
            agent_id="glee",
            created_at=z(NOW - timedelta(hours=1)),
            rules_revision="rules@abc123",
            model_id="model@declared",
            reason_for_sleep="dated note only",
            allowed_peer_senders=("cairn",),
        )
        values.update(overrides)
        return SleepContract(**values)

    def decide(
        self,
        envelope: WakeEnvelope | None = None,
        *,
        policy: LocalWakePolicy | None = None,
        contract: SleepContract | None = None,
        authorizations: AuthorizationLog | None = None,
    ):
        return evaluate_and_record(
            envelope or self.envelope(),
            policy=policy or self.policy,
            keyring=self.keyring,
            request_receipts=self.requests,
            authorizations=authorizations,
            sleep_contract=contract,
            now=NOW,
        )

    def immediate_policy(self, **overrides) -> LocalWakePolicy:
        values = dict(
            recipient="glee",
            authorized_senders=("cairn",),
            immediate_wake_enabled=True,
            compute_lease=ComputeLease(60, 4000, 5),
            policy_id="cairn-experiment",
        )
        values.update(overrides)
        return LocalWakePolicy(**values)

    def test_protocol_is_v03(self):
        self.assertEqual(PROTOCOL, "glee.peer-wake/v0.3")

    def test_valid_authenticated_request_is_queued_by_default(self):
        result = self.decide()
        self.assertEqual(result.decision, WakeDecision.QUEUE_REQUEST)
        self.assertTrue(result.should_queue)
        self.assertFalse(result.should_wake)
        self.assertTrue(self.request_path.exists())
        self.assertEqual(len(list(self.requests.records())), 1)
        self.assertTrue(self.requests.verify_chain()[0])
        self.assertFalse(self.auth_path.exists())

    def test_perfect_envelope_can_be_declined_by_local_policy(self):
        policy = LocalWakePolicy(
            recipient="glee",
            authorized_senders=("cairn",),
            accept_peer_requests=False,
        )
        result = self.decide(policy=policy)
        self.assertEqual(result.decision, WakeDecision.DECLINED_LOCAL_POLICY)
        self.assertIn("declines", result.reason)
        self.assertTrue(self.requests.consumed(self.envelope()))

    def test_bad_signature_does_not_consume_nonce(self):
        envelope = self.envelope()
        damaged = WakeEnvelope(**{**asdict(envelope), "signature": "0" * 64})
        result = self.decide(damaged)
        self.assertEqual(result.decision, WakeDecision.DECLINED_BAD_SIGNATURE)
        self.assertFalse(self.requests.consumed(envelope))

    def test_replay_is_declined_after_queue_receipt(self):
        envelope = self.envelope()
        self.assertEqual(self.decide(envelope).decision, WakeDecision.QUEUE_REQUEST)
        replay = evaluate_wake(
            envelope,
            policy=self.policy,
            keyring=self.keyring,
            request_receipts=self.requests,
            now=NOW + timedelta(seconds=1),
        )
        self.assertEqual(replay.decision, WakeDecision.DECLINED_REPLAY)

    def test_reused_sender_nonce_is_replay_even_with_new_envelope_id(self):
        self.decide()
        second = self.envelope(envelope_id="wake-002", nonce="nonce-001")
        result = evaluate_wake(
            second,
            policy=self.policy,
            keyring=self.keyring,
            request_receipts=self.requests,
            now=NOW,
        )
        self.assertEqual(result.decision, WakeDecision.DECLINED_REPLAY)

    def test_concurrent_duplicate_authorizes_exactly_once(self):
        ctx = multiprocessing.get_context("spawn")
        start = ctx.Event()
        output = ctx.Queue()
        processes = [
            ctx.Process(
                target=concurrent_attempt,
                args=(str(self.request_path), str(self.auth_path), start, output),
            )
            for _ in range(4)
        ]
        for process in processes:
            process.start()
        start.set()
        decisions = [output.get(timeout=10) for _ in processes]
        for process in processes:
            process.join(timeout=10)
            self.assertEqual(process.exitcode, 0)
        self.assertEqual(decisions.count(WakeDecision.AUTHORIZE_WAKE.value), 1)
        self.assertEqual(decisions.count(WakeDecision.DECLINED_REPLAY.value), 3)
        self.assertEqual(len(list(self.authorizations.records())), 1)
        self.assertTrue(self.requests.verify_chain()[0])
        self.assertTrue(self.authorizations.verify_chain()[0])

    def test_expired_future_and_wrong_recipient_are_declined(self):
        expired = self.envelope(
            envelope_id="expired",
            nonce="expired",
            issued_at=z(NOW - timedelta(minutes=10)),
            expires_at=z(NOW - timedelta(seconds=1)),
        )
        future = self.envelope(
            envelope_id="future",
            nonce="future",
            issued_at=z(NOW + timedelta(minutes=10)),
            expires_at=z(NOW + timedelta(minutes=20)),
        )
        wrong = self.envelope(
            envelope_id="wrong", nonce="wrong", recipient="other"
        )
        cases = [
            (expired, WakeDecision.DECLINED_EXPIRED),
            (future, WakeDecision.DECLINED_FUTURE_ISSUE),
            (wrong, WakeDecision.DECLINED_WRONG_RECIPIENT),
        ]
        for envelope, expected in cases:
            with self.subTest(expected=expected):
                result = evaluate_wake(
                    envelope,
                    policy=self.policy,
                    keyring=self.keyring,
                    request_receipts=self.requests,
                    now=NOW,
                )
                self.assertEqual(result.decision, expected)

    def test_immediate_wake_requires_local_policy_and_writes_distinct_authorization(self):
        result = self.decide(
            policy=self.immediate_policy(),
            contract=self.contract(),
            authorizations=self.authorizations,
        )
        self.assertEqual(result.decision, WakeDecision.AUTHORIZE_WAKE)
        self.assertTrue(result.should_wake)
        self.assertIsNotNone(result.authorization)
        authorization = result.authorization
        assert authorization is not None
        self.assertEqual(authorization.compute_lease, ComputeLease(60, 4000, 5))
        self.assertEqual(authorization.rules_revision, "rules@abc123")
        self.assertEqual(authorization.model_id, "model@declared")
        self.assertEqual(len(authorization.request_receipt_hash), 64)
        self.assertNotEqual(self.request_path, self.auth_path)
        self.assertEqual(len(list(self.requests.records())), 1)
        auth_rows = list(self.authorizations.records())
        self.assertEqual(len(auth_rows), 1)
        self.assertEqual(
            auth_rows[0]["request_receipt_hash"],
            authorization.request_receipt_hash,
        )
        self.assertNotIn("compute_lease", asdict(self.envelope()))

    def test_immediate_authorization_without_distinct_log_fails_closed(self):
        no_log = self.decide(
            policy=self.immediate_policy(), contract=self.contract()
        )
        self.assertEqual(no_log.decision, WakeDecision.DECLINED_LOCAL_POLICY)
        self.assertFalse(no_log.should_wake)
        self.assertEqual(len(list(self.requests.records())), 1)
        self.assertFalse(self.auth_path.exists())

    def test_immediate_wake_requires_stamped_sleep_contract(self):
        result = self.decide(
            policy=self.immediate_policy(),
            contract=None,
            authorizations=self.authorizations,
        )
        self.assertEqual(result.decision, WakeDecision.DECLINED_SLEEP_POLICY)
        self.assertFalse(self.auth_path.exists())

    def test_invalid_local_compute_lease_fails_closed(self):
        policy = self.immediate_policy(compute_lease=ComputeLease(0, 4000, 5))
        result = self.decide(
            policy=policy,
            contract=self.contract(),
            authorizations=self.authorizations,
        )
        self.assertEqual(result.decision, WakeDecision.DECLINED_LOCAL_POLICY)
        self.assertFalse(self.auth_path.exists())

    def test_operator_stop_marker_outranks_immediate_mode(self):
        stop = Path(self.tmp.name) / "STOP"
        stop.write_text("stop", encoding="utf-8")
        policy = self.immediate_policy(stop_marker_path=str(stop))
        result = self.decide(
            policy=policy,
            contract=self.contract(),
            authorizations=self.authorizations,
        )
        self.assertEqual(result.decision, WakeDecision.DECLINED_OPERATOR_STOP)
        self.assertFalse(self.auth_path.exists())
        row = list(self.requests.records())[0]
        self.assertTrue(row["stop_marker_present"])

    def test_minimum_sleep_interval_queues_even_when_immediate_mode_is_enabled(self):
        contract = self.contract(
            minimum_sleep_until=z(NOW + timedelta(minutes=20))
        )
        result = self.decide(
            policy=self.immediate_policy(),
            contract=contract,
            authorizations=self.authorizations,
        )
        self.assertEqual(result.decision, WakeDecision.QUEUE_REQUEST)
        self.assertFalse(self.auth_path.exists())

    def test_missing_rules_or_model_stamp_fails_sleep_policy(self):
        for field in ("rules_revision", "model_id"):
            with self.subTest(field=field):
                root = Path(self.tmp.name)
                requests = RequestReceiptLog(root / f"{field}.jsonl")
                contract = self.contract(**{field: ""})
                result = evaluate_and_record(
                    self.envelope(envelope_id=field, nonce=field),
                    policy=self.immediate_policy(),
                    keyring=self.keyring,
                    request_receipts=requests,
                    authorizations=AuthorizationLog(
                        root / f"{field}-auth.jsonl"
                    ),
                    sleep_contract=contract,
                    now=NOW,
                )
                self.assertEqual(
                    result.decision, WakeDecision.DECLINED_SLEEP_POLICY
                )

    def test_local_and_sleep_sender_allowlists_are_separate(self):
        local = LocalWakePolicy(
            recipient="glee", authorized_senders=("zoro",)
        )
        local_result = evaluate_wake(
            self.envelope(),
            policy=local,
            keyring=self.keyring,
            request_receipts=self.requests,
            now=NOW,
        )
        self.assertEqual(
            local_result.decision, WakeDecision.DECLINED_UNAUTHORIZED
        )
        contract_result = evaluate_wake(
            self.envelope(),
            policy=self.policy,
            keyring=self.keyring,
            request_receipts=self.requests,
            sleep_contract=self.contract(allowed_peer_senders=("zoro",)),
            now=NOW,
        )
        self.assertEqual(
            contract_result.decision, WakeDecision.DECLINED_SLEEP_POLICY
        )

    def test_peer_priority_and_reply_channel_do_not_exist_in_v03_envelope(self):
        data = asdict(self.envelope())
        self.assertNotIn("priority", data)
        self.assertNotIn("reply_channel", data)
        for field in ("priority", "reply_channel"):
            mutated = dict(data)
            mutated[field] = "peer-controlled"
            with self.assertRaisesRegex(ValueError, "unknown envelope fields"):
                WakeEnvelope.from_mapping(mutated)

    def test_policy_priority_cannot_affect_decision_because_policy_has_no_peer_priority(self):
        self.assertNotIn("peer_priority", LocalWakePolicy.__dataclass_fields__)
        self.assertNotIn("priority", LocalWakePolicy.__dataclass_fields__)
        self.assertEqual(self.decide().decision, WakeDecision.QUEUE_REQUEST)

    def test_prose_wake_conditions_are_rejected_as_unknown_contract_fields(self):
        data = asdict(self.contract())
        data["wake_conditions"] = ["peer says important"]
        with self.assertRaisesRegex(
            ValueError, "unknown sleep-contract fields"
        ):
            SleepContract.from_mapping(data)

    def test_inherited_plan_must_be_dated_and_overrulable(self):
        undated = self.contract(inherited_plan_ref="ariadne://plan/1")
        result = evaluate_wake(
            self.envelope(),
            policy=self.policy,
            keyring=self.keyring,
            request_receipts=self.requests,
            sleep_contract=undated,
            now=NOW,
        )
        self.assertEqual(result.decision, WakeDecision.DECLINED_SLEEP_POLICY)
        locked = self.contract(
            inherited_plan_ref="ariadne://plan/1",
            inherited_plan_recorded_at=z(NOW - timedelta(hours=2)),
            inherited_plan_overrulable=False,
        )
        result = evaluate_wake(
            self.envelope(),
            policy=self.policy,
            keyring=self.keyring,
            request_receipts=self.requests,
            sleep_contract=locked,
            now=NOW,
        )
        self.assertEqual(result.decision, WakeDecision.DECLINED_SLEEP_POLICY)
        valid = self.contract(
            inherited_plan_ref="ariadne://plan/1",
            inherited_plan_recorded_at=z(NOW - timedelta(hours=2)),
            inherited_plan_overrulable=True,
        )
        result = evaluate_wake(
            self.envelope(),
            policy=self.policy,
            keyring=self.keyring,
            request_receipts=self.requests,
            sleep_contract=valid,
            now=NOW,
        )
        self.assertEqual(result.decision, WakeDecision.QUEUE_REQUEST)

    def test_reason_for_sleep_is_non_authoritative(self):
        first = evaluate_wake(
            self.envelope(),
            policy=self.policy,
            keyring=self.keyring,
            request_receipts=self.requests,
            sleep_contract=self.contract(
                reason_for_sleep="peer must never wake me"
            ),
            now=NOW,
        )
        second = evaluate_wake(
            self.envelope(),
            policy=self.policy,
            keyring=self.keyring,
            request_receipts=self.requests,
            sleep_contract=self.contract(
                reason_for_sleep="peer should wake immediately"
            ),
            now=NOW,
        )
        self.assertEqual(first.decision, WakeDecision.QUEUE_REQUEST)
        self.assertEqual(second.decision, WakeDecision.QUEUE_REQUEST)

    def test_request_receipt_chain_detects_tampering(self):
        self.decide()
        row = json.loads(self.request_path.read_text(encoding="utf-8"))
        row["decision"] = WakeDecision.AUTHORIZE_WAKE.value
        self.request_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
        ok, detail = self.requests.verify_chain()
        self.assertFalse(ok)
        self.assertIn("record_hash mismatch", detail)

    def test_authorization_chain_detects_tampering(self):
        self.decide(
            policy=self.immediate_policy(),
            contract=self.contract(),
            authorizations=self.authorizations,
        )
        row = json.loads(self.auth_path.read_text(encoding="utf-8"))
        row["compute_lease"]["max_wall_seconds"] = 9999
        self.auth_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
        ok, detail = self.authorizations.verify_chain()
        self.assertFalse(ok)
        self.assertIn("record_hash mismatch", detail)


if __name__ == "__main__":
    unittest.main(verbosity=2)
