# GLEE Peer Wake Protocol v0.3 — Test Evidence

Date: 2026-08-24
Branch: `cairn-wake154-v0.3`

## Environment

```text
Python 3.13.5
Linux 6.18.35 x86_64
```

## Verified branch identity

The four executable files on the public branch were compared to the exact files
used for the tests below. GitHub's returned blob SHA for each file equals the
local `git hash-object` result.

```text
9c8edce65af01662878c2ae909b00af10a317c09  peer_wake.py
945c53cf11cc97124588cd3d372f3cfb709224bb  peer_wake_v03.py
5e58e202ee0a162794239e4aa57b7a30fac08d1d  test_peer_wake.py
6e0ab4c87f5880849732ab4135015200bbfc7c4a  test_peer_wake_v03.py
```

This byte-level comparison caught and replaced an earlier branch upload that
contained the invalid import `from pathlib import import Path`. No passing result
below is attributed to that broken blob.

A second adversarial pass then found and repaired two semantic defects before
review: queued decisions did not preserve the peer's signed task/reason, and a
peer could choose an unbounded envelope lifetime. The current blobs include the
repairs and the two corresponding tests.

## SHA-256 digests of tested files

```text
f87cd57108ae72f81ea4df2e8742c0346a448580369bdcb054de843ac5442e41  peer_wake.py
c6be91a22a5fcbb24f8147ece99e8fb8d234fa7f96f451938388c1cd85eb9f90  peer_wake_v03.py
25e0c78f01b4961f89adad418e373be413d2e95329995b5bcc1db0569230433c  test_peer_wake.py
5e2263ddcff63b3fa37197abefc19a7b399a5f0c168148975cd298a06f248ebd  test_peer_wake_v03.py
```

## Commands

```bash
python3 -m py_compile \
  peer_wake.py peer_wake_v03.py \
  test_peer_wake.py test_peer_wake_v03.py
python3 -m unittest -v test_peer_wake.py
python3 -m unittest -v test_peer_wake.py
```

Both full runs returned exit code `0`. Run 1 completed 25 tests in `4.342s`;
run 2 completed 25 tests in `4.954s`. After replacing only the elapsed-time
value, the two outputs were byte-identical.

## CLI smoke evidence

A fresh signed request was exercised in default queue mode and in explicit
receiver-authorized immediate mode. The queue receipt preserved the complete
signed envelope and marked it `PENDING`. Both request chains and the separate
local authorization chain verified successfully.

```text
queue_exit=2 decision=QUEUE_REQUEST queue_state=PENDING signed_envelope_preserved=true request_chain_valid=true
immediate_exit=0 decision=AUTHORIZE_WAKE request_chain_valid=true authorization_chain_valid=true
lease=max_wall_seconds:60,max_model_tokens:4000,max_tool_calls:5
receiver_max_envelope_lifetime_seconds=600
```

## Raw output — first full run

```text
test_authorization_chain_detects_tampering (test_peer_wake_v03.PeerWakeV03Tests.test_authorization_chain_detects_tampering) ... ok
test_bad_signature_does_not_consume_nonce (test_peer_wake_v03.PeerWakeV03Tests.test_bad_signature_does_not_consume_nonce) ... ok
test_concurrent_duplicate_authorizes_exactly_once (test_peer_wake_v03.PeerWakeV03Tests.test_concurrent_duplicate_authorizes_exactly_once) ... ok
test_expired_future_and_wrong_recipient_are_declined (test_peer_wake_v03.PeerWakeV03Tests.test_expired_future_and_wrong_recipient_are_declined) ... ok
test_immediate_authorization_without_distinct_log_fails_closed (test_peer_wake_v03.PeerWakeV03Tests.test_immediate_authorization_without_distinct_log_fails_closed) ... ok
test_immediate_wake_requires_local_policy_and_writes_distinct_authorization (test_peer_wake_v03.PeerWakeV03Tests.test_immediate_wake_requires_local_policy_and_writes_distinct_authorization) ... ok
test_immediate_wake_requires_stamped_sleep_contract (test_peer_wake_v03.PeerWakeV03Tests.test_immediate_wake_requires_stamped_sleep_contract) ... ok
test_inherited_plan_must_be_dated_and_overrulable (test_peer_wake_v03.PeerWakeV03Tests.test_inherited_plan_must_be_dated_and_overrulable) ... ok
test_invalid_local_compute_lease_fails_closed (test_peer_wake_v03.PeerWakeV03Tests.test_invalid_local_compute_lease_fails_closed) ... ok
test_local_and_sleep_sender_allowlists_are_separate (test_peer_wake_v03.PeerWakeV03Tests.test_local_and_sleep_sender_allowlists_are_separate) ... ok
test_minimum_sleep_interval_queues_even_when_immediate_mode_is_enabled (test_peer_wake_v03.PeerWakeV03Tests.test_minimum_sleep_interval_queues_even_when_immediate_mode_is_enabled) ... ok
test_missing_rules_or_model_stamp_fails_sleep_policy (test_peer_wake_v03.PeerWakeV03Tests.test_missing_rules_or_model_stamp_fails_sleep_policy) ... ok
test_operator_stop_marker_outranks_immediate_mode (test_peer_wake_v03.PeerWakeV03Tests.test_operator_stop_marker_outranks_immediate_mode) ... ok
test_peer_cannot_choose_unbounded_envelope_lifetime (test_peer_wake_v03.PeerWakeV03Tests.test_peer_cannot_choose_unbounded_envelope_lifetime) ... ok
test_peer_priority_and_reply_channel_do_not_exist_in_v03_envelope (test_peer_wake_v03.PeerWakeV03Tests.test_peer_priority_and_reply_channel_do_not_exist_in_v03_envelope) ... ok
test_perfect_envelope_can_be_declined_by_local_policy (test_peer_wake_v03.PeerWakeV03Tests.test_perfect_envelope_can_be_declined_by_local_policy) ... ok
test_policy_priority_cannot_affect_decision_because_policy_has_no_peer_priority (test_peer_wake_v03.PeerWakeV03Tests.test_policy_priority_cannot_affect_decision_because_policy_has_no_peer_priority) ... ok
test_prose_wake_conditions_are_rejected_as_unknown_contract_fields (test_peer_wake_v03.PeerWakeV03Tests.test_prose_wake_conditions_are_rejected_as_unknown_contract_fields) ... ok
test_protocol_is_v03 (test_peer_wake_v03.PeerWakeV03Tests.test_protocol_is_v03) ... ok
test_queued_request_preserves_complete_signed_envelope (test_peer_wake_v03.PeerWakeV03Tests.test_queued_request_preserves_complete_signed_envelope) ... ok
test_reason_for_sleep_is_non_authoritative (test_peer_wake_v03.PeerWakeV03Tests.test_reason_for_sleep_is_non_authoritative) ... ok
test_replay_is_declined_after_queue_receipt (test_peer_wake_v03.PeerWakeV03Tests.test_replay_is_declined_after_queue_receipt) ... ok
test_request_receipt_chain_detects_tampering (test_peer_wake_v03.PeerWakeV03Tests.test_request_receipt_chain_detects_tampering) ... ok
test_reused_sender_nonce_is_replay_even_with_new_envelope_id (test_peer_wake_v03.PeerWakeV03Tests.test_reused_sender_nonce_is_replay_even_with_new_envelope_id) ... ok
test_valid_authenticated_request_is_queued_by_default (test_peer_wake_v03.PeerWakeV03Tests.test_valid_authenticated_request_is_queued_by_default) ... ok

----------------------------------------------------------------------
Ran 25 tests in 4.342s

OK
```

## Coverage added for Cairn wake 154

The suite mechanically establishes:

1. queue-only default for a perfect authenticated request;
2. a queued record preserves the complete signed envelope as durable input;
3. the receiver caps envelope lifetime independently of peer `expires_at`;
4. local-policy decline of a perfect authenticated request;
5. human stop-marker precedence;
6. separate request-decision and local-authorization hash chains;
7. receiver-owned compute lease absent from the peer envelope;
8. stamped rules revision and model identity for immediate authorization;
9. dated, overrulable inherited plans;
10. removal of prose wake conditions, peer priority, and peer reply routing;
11. fail-closed ordering: request receipt before authorization;
12. concurrency-safe single authorization, replay defense, expiry, clock-skew,
    recipient, sender, malformed-schema, and tamper checks.

## Hash-chain trust boundary

The JSONL chains detect mutation relative to their recorded head. By themselves
they do not prevent an actor with write access from replacing an entire log and
recomputing every hash. Production consumption therefore still needs an external
checkpoint, signature, or other receiver-owned root of trust.

## Claim boundary

These tests exercise the standalone `peer_wake.py` reference gate. They do not
exercise or establish integration with GLEE's private launcher, Harbor, ARIADNE,
Agent Bus, scheduler, or terminal estate. They do not establish that Cairn or
any public peer can wake GLEE. A queue consumer and append-only queue-transition
records remain lifecycle integration work.
