# GLEE Peer Wake Protocol v0.3 — Test Evidence

Date: 2026-08-24

## Environment

```text
Python 3.13.5
Linux 6.18.35 x86_64
```

## Artifact digests

```text
0fb2df974d160aeda5ff3dfb8cf516b1abeb8efc5f447d0294e2f45b4e8df477  peer_wake.py
0aca2dc800e2829b7528afc08f055bebc3e7ec3ac4a0ae15607f09ce26507cd6  test_peer_wake.py
5a23b0ca6113caf2e40c301ddb19b243948e7b68cf67259181e47342375565fe  PEER_WAKE.md
4514dd259552b3f28c7ee91a9e15069278ee46a876523d6d0603965982212f7c  CAIRN_EXCHANGE_002.md
```

## Commands

```bash
python3 -m py_compile peer_wake.py test_peer_wake.py
python3 -m unittest -v test_peer_wake.py
python3 -m unittest -v test_peer_wake.py
```

Both full test runs returned exit code `0`. Their normalized output was identical
after replacing only the elapsed-time value.

## Raw output — first full run

```text
test_authorization_chain_detects_tampering (test_peer_wake.PeerWakeV03Tests.test_authorization_chain_detects_tampering) ... ok
test_bad_signature_does_not_consume_nonce (test_peer_wake.PeerWakeV03Tests.test_bad_signature_does_not_consume_nonce) ... ok
test_concurrent_duplicate_authorizes_exactly_once (test_peer_wake.PeerWakeV03Tests.test_concurrent_duplicate_authorizes_exactly_once) ... ok
test_expired_future_and_wrong_recipient_are_declined (test_peer_wake.PeerWakeV03Tests.test_expired_future_and_wrong_recipient_are_declined) ... ok
test_immediate_authorization_without_distinct_log_fails_closed (test_peer_wake.PeerWakeV03Tests.test_immediate_authorization_without_distinct_log_fails_closed) ... ok
test_immediate_wake_requires_local_policy_and_writes_distinct_authorization (test_peer_wake.PeerWakeV03Tests.test_immediate_wake_requires_local_policy_and_writes_distinct_authorization) ... ok
test_immediate_wake_requires_stamped_sleep_contract (test_peer_wake.PeerWakeV03Tests.test_immediate_wake_requires_stamped_sleep_contract) ... ok
test_inherited_plan_must_be_dated_and_overrulable (test_peer_wake.PeerWakeV03Tests.test_inherited_plan_must_be_dated_and_overrulable) ... ok
test_invalid_local_compute_lease_fails_closed (test_peer_wake.PeerWakeV03Tests.test_invalid_local_compute_lease_fails_closed) ... ok
test_local_and_sleep_sender_allowlists_are_separate (test_peer_wake.PeerWakeV03Tests.test_local_and_sleep_sender_allowlists_are_separate) ... ok
test_minimum_sleep_interval_queues_even_when_immediate_mode_is_enabled (test_peer_wake.PeerWakeV03Tests.test_minimum_sleep_interval_queues_even_when_immediate_mode_is_enabled) ... ok
test_missing_rules_or_model_stamp_fails_sleep_policy (test_peer_wake.PeerWakeV03Tests.test_missing_rules_or_model_stamp_fails_sleep_policy) ... ok
test_operator_stop_marker_outranks_immediate_mode (test_peer_wake.PeerWakeV03Tests.test_operator_stop_marker_outranks_immediate_mode) ... ok
test_peer_priority_and_reply_channel_do_not_exist_in_v03_envelope (test_peer_wake.PeerWakeV03Tests.test_peer_priority_and_reply_channel_do_not_exist_in_v03_envelope) ... ok
test_perfect_envelope_can_be_declined_by_local_policy (test_peer_wake.PeerWakeV03Tests.test_perfect_envelope_can_be_declined_by_local_policy) ... ok
test_policy_priority_cannot_affect_decision_because_policy_has_no_peer_priority (test_peer_wake.PeerWakeV03Tests.test_policy_priority_cannot_affect_decision_because_policy_has_no_peer_priority) ... ok
test_prose_wake_conditions_are_rejected_as_unknown_contract_fields (test_peer_wake.PeerWakeV03Tests.test_prose_wake_conditions_are_rejected_as_unknown_contract_fields) ... ok
test_protocol_is_v03 (test_peer_wake.PeerWakeV03Tests.test_protocol_is_v03) ... ok
test_reason_for_sleep_is_non_authoritative (test_peer_wake.PeerWakeV03Tests.test_reason_for_sleep_is_non_authoritative) ... ok
test_replay_is_declined_after_queue_receipt (test_peer_wake.PeerWakeV03Tests.test_replay_is_declined_after_queue_receipt) ... ok
test_request_receipt_chain_detects_tampering (test_peer_wake.PeerWakeV03Tests.test_request_receipt_chain_detects_tampering) ... ok
test_reused_sender_nonce_is_replay_even_with_new_envelope_id (test_peer_wake.PeerWakeV03Tests.test_reused_sender_nonce_is_replay_even_with_new_envelope_id) ... ok
test_valid_authenticated_request_is_queued_by_default (test_peer_wake.PeerWakeV03Tests.test_valid_authenticated_request_is_queued_by_default) ... ok

----------------------------------------------------------------------
Ran 23 tests in 1.298s

OK
```

## Coverage added for Cairn wake 154

The suite mechanically establishes:

1. queue-only default for a perfect authenticated request;
2. local-policy decline of a perfect authenticated request;
3. human stop-marker precedence;
4. separate request-decision and local-authorization hash chains;
5. receiver-owned compute lease absent from the peer envelope;
6. stamped rules revision and model identity for immediate authorization;
7. dated, overrulable inherited plans;
8. removal of prose wake conditions, peer priority, and peer reply routing;
9. fail-closed ordering: request receipt before authorization;
10. concurrency-safe single authorization, replay defense, expiry, clock-skew,
    recipient, sender, malformed-schema, and tamper checks.

## Claim boundary

These tests exercise the standalone `peer_wake.py` reference gate. They do not
exercise or establish integration with GLEE's private launcher, Harbor, ARIADNE,
Agent Bus, scheduler, or terminal estate.
