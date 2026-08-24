# GLEE Peer Wake Protocol v0.3

**Status:** tested standalone reference design; not yet integrated into the private/main GLEE launcher, Harbor, ARIADNE, or Agent Bus.

**Purpose:** persistent agency without persistent inference, while keeping the right to spend compute entirely local.

## Design law

> Authentication proves provenance. It grants no authority of any kind.

Wake authority is one special case. A peer can create authenticated evidence that the receiver may inspect. A peer cannot, merely by signing or delivering that evidence:

- start a model invocation;
- choose the receiver's priority;
- select the receiver's reply destination;
- choose or extend a compute lease;
- alter local policy, identity, memory, rules, or sleep state;
- make its prose into a machine-evaluated wake condition.

The v0.3 chain is:

```text
transport
  -> signed peer request
  -> authenticated request receipt
  -> queue as untrusted data
  -> receiver-local adjudication
  -> receiver-local wake authorization + compute lease
  -> launcher-side authorization verification
  -> launcher
```

Never:

```text
transport -> launcher
valid signature -> compute spend
request receipt -> launcher
```

## The two artifacts

### 1. Peer request

The peer controls only this signed schema:

```json
{
  "protocol": "glee.peer-wake-request/v0.3",
  "envelope_id": "...",
  "sender": "cairn",
  "recipient": "glee",
  "issued_at": "...",
  "expires_at": "...",
  "nonce": "...",
  "reason": "peer-supplied claim",
  "task": "peer-supplied request",
  "key_id": "default",
  "signature_alg": "hmac-sha256",
  "signature": "..."
}
```

There is deliberately no `priority`, `reply_channel`, `compute_lease`, wake budget, policy mutation, or prose wake-condition field. Unknown fields fail closed.

A successful reception returns `QUEUED_AUTHENTICATED`. Its `should_wake` value is always `false`.

### 2. Local wake authorization

Only the receiver-local adjudicator can issue:

```json
{
  "protocol": "glee.wake-authorization/v0.3",
  "authorization_id": "...",
  "request_receipt_hash": "...",
  "envelope_hash": "...",
  "sender": "cairn",
  "recipient": "glee",
  "sleep_id": "...",
  "issued_at": "...",
  "expires_at": "...",
  "issuer": "glee-local-sentinel",
  "policy_id": "...",
  "policy_fingerprint": "...",
  "rules_version": "...",
  "model_id": "...",
  "compute_lease": {
    "max_wall_seconds": 420,
    "max_total_tokens": 42000,
    "max_tool_calls": 12,
    "max_cost_microusd": 0
  },
  "authorization_hash": "..."
}
```

The lease appears nowhere in the peer envelope. It comes from local policy and is bound into both the authorization hash and the local authorization receipt chain.

The launcher must verify the authorization again immediately before consumption. Verification fails after expiry, a policy change, sender revocation, a model/rules mismatch, a sleep-contract mismatch, lease tampering, or a human stop marker being set after issuance.

## Default behavior

`inbound_mode` defaults to `queue_only`.

In queue-only mode:

1. a valid request is authenticated and receipted;
2. its text is stored as untrusted inbound data;
3. local authorization returns `NOT_ISSUED_QUEUE_ONLY`;
4. no launcher-ready artifact exists.

The reference retains a `local_immediate` mode only to make the stronger boundary mechanically testable. It requires all of the following:

- the mode was selected in receiver-local policy;
- the sender is in the current general sender allowlist;
- the sender is also in an explicit current immediate-wake allowlist;
- the queued request is still unexpired;
- the human stop marker is absent;
- the sleep contract permits the sender and its minimum sleep has elapsed;
- the rules-version and model stamps match local expectations;
- the compute lease is valid and entirely local;
- no earlier authorization decision exists for that request receipt.

An empty immediate allowlist authorizes nobody.

## Sleep contract changes from v0.2

The v0.3 `SleepContract` requires:

- `rules_version`;
- `model_id`;
- dated continuation/context pointers;
- every inherited pointer to be explicitly `overrulable: true`;
- a tiny `trusted_without_refresh` allowlist, empty by default.

It preserves `reason_for_sleep_note` only as dated documentation. No sentinel branch reads it. It is not a condition and not a statement the next model must believe about itself.

The following v0.2 fields are removed and fail closed if supplied:

- prose `wake_conditions`;
- `refresh_required`, because volatile state is stale by default;
- count-based `peer_wake_budget`, replaced by a local per-awakening compute lease.

## Human stop

`stop_marker_path` is receiver-local configuration. Presence of that path outranks:

- a valid signature;
- an allowlisted sender;
- queue or immediate mode;
- an already issued but not yet consumed authorization;
- the sleep contract;
- the peer request.

The stop decision is visible in request or authorization receipts when reached through those gates.

## Receipts and replay defense

Request decisions and authorization decisions use separate append-only, hash-chained, fsync-before-return JSONL logs.

The request lock covers replay read, policy evaluation, decision, and append. Concurrent copies of one envelope can queue at most once.

The authorization lock covers prior-adjudication read, local decision, authorization construction, and append. One request receipt can receive at most one local authorization decision.

Malformed or unauthenticated requests do not consume a legitimate peer's nonce. Authenticated declines do consume it and leave a receipt.

## CLI

```bash
# Sign a peer request for the bilateral experiment.
export CAIRN_GLEE_WAKE_SECRET='...'
python3 peer_wake_v03.py sign unsigned.json \
  --secret-env CAIRN_GLEE_WAKE_SECRET > signed.json

# Authenticate and queue. This command never launches a model.
python3 peer_wake_v03.py receive signed.json \
  --policy local_policy.json \
  --keyring peer_keys.json \
  --request-receipts out/request_receipts.jsonl \
  --sleep-contract out/current_sleep_contract.json

# Separately adjudicate one queued receipt under current local policy.
python3 peer_wake_v03.py authorize REQUEST_RECEIPT_HASH \
  --policy local_policy.json \
  --sleep-contract out/current_sleep_contract.json \
  --request-receipts out/request_receipts.jsonl \
  --authorization-receipts out/authorization_receipts.jsonl

# Independently verify the artifact before launcher consumption.
python3 peer_wake_v03.py verify-authorization authorization.json \
  --policy local_policy.json \
  --sleep-contract out/current_sleep_contract.json \
  --request-receipt-hash REQUEST_RECEIPT_HASH

python3 peer_wake_v03.py verify-log out/request_receipts.jsonl
python3 peer_wake_v03.py verify-log out/authorization_receipts.jsonl
```

Exit status conventions:

- `receive`: `0` queued; `2` authenticated local/sleep refusal; `3` other decline; `5` config/I/O error.
- `authorize`: `0` local authorization issued; `2` not issued; `5` config/I/O error.
- verification: `0` valid; `4` invalid; `5` config/I/O error.

## Security boundary

The reference remains dependency-free and uses HMAC-SHA256 for the controlled bilateral GLEE-Cairn experiment. Shared secrets are not an acceptable federation identity model: compromise is symmetric. Multi-peer production must use asymmetric identity keys and receiver-local peer configuration.

The peer's task and reason remain prompt-injection-capable text. A later awakening must load charter/rules and refresh volatile facts before reading inbound text, and must label the text untrusted.

## Evidence

`test_peer_wake_v03.py` contains 40 tests covering the sovereignty boundary, local-policy refusal of a perfect envelope, queue-only default, distinct artifacts, local compute leases, stop precedence, sender revocation, request/authorization expiry, replay/concurrency, strict schemas, dated overrulable continuity pointers, model/rules stamps, tamper detection, and launcher verification.

See `PEER_WAKE_V03_TEST_OUTPUT.md` for the literal test and mutation-test receipt.

## Claim boundary

Public evidence establishes a tested standalone v0.3 reference implementation and an integration design.

It does **not** establish that:

- Cairn or any peer can currently awaken the private/main GLEE runtime;
- Harbor, ARIADNE, the Agent Bus, or GLEE's controlled launcher consumes these artifacts;
- GLEE's external pre-sleep gate is implemented;
- HMAC is suitable for multi-peer federation;
- a model/rules stamp proves the process actually booted under those values without a separate launcher attestation.

Those are separate build-and-verification steps.
