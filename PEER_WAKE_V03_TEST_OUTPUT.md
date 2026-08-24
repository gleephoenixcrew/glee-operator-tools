# GLEE Peer Wake v0.3 — Test and Mutation Receipt

Date: 2026-08-24

## Environment

```text
Python 3.13.5
```

No third-party Python dependencies are required. `ruff` was not installed in the isolated build environment, so no ruff result is claimed. Python compilation, unit/integration tests, CLI smoke tests, hash-chain verification, and targeted mutation probes were run.

## Deterministic suite

Command:

```bash
python3 -m compileall -q peer_wake_v03.py test_peer_wake_v03.py
python3 test_peer_wake_v03.py
python3 test_peer_wake_v03.py
```

Run 1:

```text
Ran 40 tests in 2.321s

OK
```

Run 2:

```text
Ran 40 tests in 1.752s

OK
```

The suite covers:

- valid authenticated request queues but never wakes;
- no sleep contract is not permissive immediate wake;
- a perfect valid envelope can be declined solely by local policy;
- queue-only authorization refusal;
- separate local authorization and local compute lease;
- explicit immediate sender pre-authorization;
- sender revocation after queueing;
- request expiry before authorization;
- authorization expiry before launcher consumption;
- human stop before request, before authorization, and after authorization;
- rules/model/sleep-contract binding;
- unknown `priority`, `reply_channel`, `compute_lease`, prose wake conditions, and old refresh fields;
- dated, explicitly overrulable continuation pointers;
- bad-signature nonce preservation;
- envelope and nonce replay;
- four-process concurrent duplicate serialization;
- request and authorization receipt-chain tamper detection;
- authorization-hash and lease tamper detection;
- launcher-side verification under current local policy.

## CLI smoke proof

The CLI was exercised end to end with generated current timestamps:

```text
receive_decision:                 QUEUED_AUTHENTICATED
receive_should_wake:              false
queue_authorization_decision:     NOT_ISSUED_QUEUE_ONLY
queue_should_wake:                false
queue_authorize_exit:             2
immediate_authorization_decision: AUTHORIZED
immediate_should_wake:            true
local_lease_max_total_tokens:     42000
authorization_valid:              true
request_chain_valid:              true
authorization_chain_valid:        true
```

The immediate case used a separate local policy with an explicit sender allowlist and local lease. It is a reference falsification path, not GLEE's current bilateral posture; current posture is queue-only.

## Mutation probes

Three load-bearing mechanisms were deliberately broken in isolated copies. Each mutation caused its corresponding test to fail.

### Mutation 1 — let a request receipt claim wake authority

Changed `RequestResult.should_wake` from constant `False` to `self.queued`.

```text
AssertionError: True is not false
mutation exit: 1
```

### Mutation 2 — remove explicit immediate sender pre-authorization

Disabled the branch that refuses a sender missing from `immediate_senders`.

```text
AssertionError: AUTHORIZED != NOT_ISSUED_LOCAL_POLICY
mutation exit: 1
```

### Mutation 3 — disable the human stop check at authorization

Disabled the stop-marker branch before authorization issuance.

```text
AssertionError: AUTHORIZED != NOT_ISSUED_STOPPED
mutation exit: 1
```

These probes do not prove total test adequacy. They establish that the three central sovereignty tests are not vacuous with respect to their intended branches.

## SHA-256 digests

```text
3733f63d06946d93c6a6872482c6978ccfd51f963e10261f9a7dbf3eea63c619  peer_wake_v03.py
7ef116990981ef6236b8ca04cde6fd234a970e65e1dd3f6f89f4d3cd804cee28  test_peer_wake_v03.py
```

## Claim boundary

This receipt proves only the standalone artifact as tested in the isolated environment. It does not prove private/main GLEE integration, live peer-triggered launch, production asymmetric identity, or external pre-sleep sealing.
