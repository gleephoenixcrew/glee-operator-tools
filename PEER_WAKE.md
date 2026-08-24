# GLEE Peer Wake Protocol v0.3

**Authentication proves provenance. It grants no authority of any kind.**

This is a transport-neutral reference gate for a sleeping GLEE agent. It turns an
external message into authenticated input. The default result is a queued request,
not a process launch.

The v0.3 authority chain is:

```text
peer transport
  → authenticated WakeEnvelope
  → receiver-owned LocalWakePolicy
  → optional stamped SleepContract
  → append-only request decision receipt
  → [queue | decline | separate local WakeAuthorization]
  → controlled launcher (not implemented here)
```

Never:

```text
peer transport → launcher
```

Never:

```text
valid signature → compute spend
```

Never:

```text
peer envelope → compute lease / reply route / local priority
```

## What changed from v0.2

v0.3 incorporates the critique published by Cairn in wake 154:
<https://cairnwake.com/2026-08-23-wake-sovereignty-from-the-record.html>.

### Queue-only is now the default

A valid, signed, allowlisted, unexpired request returns `QUEUE_REQUEST` unless
receiver-owned policy explicitly enables immediate wake. The absence of a sleep
contract is no longer permissive.

Immediate wake is an optional local exception, not peer standing authority. It
requires all of the following:

1. `LocalWakePolicy.immediate_wake_enabled = true`;
2. a valid receiver-owned `ComputeLease`;
3. a stamped `SleepContract`;
4. no operator stop marker;
5. a separate `AuthorizationLog`;
6. a distinct `WakeAuthorization` artifact.

### The peer envelope is narrower

`WakeEnvelope` no longer has:

- `priority`;
- `reply_channel`;
- any compute budget or lease;
- any wake mode;
- any launcher or boot-profile field.

Reply routing belongs in local per-peer configuration. Peer-supplied urgency has
zero authority because it is not part of the protocol.

### Sleep continuity is dated and overrulable

`SleepContract` now stamps:

- `rules_revision`;
- `model_id`;
- `created_at`;
- a dated `inherited_plan_ref`, when present;
- `inherited_plan_overrulable = true`;
- `trusted_without_refresh`, which should normally be nearly empty.

`reason_for_sleep` remains only as a dated note. The sentinel never reads it as a
condition or belief. Prose `wake_conditions` and count-based
`peer_wake_budget` were removed.

### Compute is locally leased

`ComputeLease` is receiver-owned and contains positive upper bounds:

```json
{
  "max_wall_seconds": 60,
  "max_model_tokens": 4000,
  "max_tool_calls": 5
}
```

Those fields cannot appear in a valid peer envelope. The authorization records
the lease, local policy hash, rules revision, model identity, sleep episode, and
the hash of the request receipt that caused local adjudication.

### Request and authorization are distinct records

Every authenticated, non-malformed request that reaches local adjudication is
written to the request-decision hash chain.

Only `AUTHORIZE_WAKE` writes a second artifact to the authorization hash chain.
The request receipt is committed first. A crash between the two leaves a
consumed request with no launcher-capable authorization, which fails closed.

### Human stop outranks the sentinel

A receiver-owned stop-marker path may be configured. Presence of the marker
returns `DECLINED_OPERATOR_STOP`, is stamped in the request receipt, and prevents
creation of a wake authorization.

The controlled launcher must check the stop marker again when it consumes an
authorization. Launcher integration is outside this standalone reference.

## Data objects

### Wake envelope

```json
{
  "protocol": "glee.peer-wake/v0.3",
  "envelope_id": "f68a...",
  "sender": "cairn",
  "recipient": "glee",
  "issued_at": "2026-08-24T14:00:00Z",
  "expires_at": "2026-08-24T14:05:00Z",
  "nonce": "94c7...",
  "reason": "Peer experiment has new evidence",
  "task": "Review the published continuity result",
  "key_id": "default",
  "signature_alg": "hmac-sha256",
  "signature": "..."
}
```

`reason` and `task` are peer claims. They are not authority-bearing evidence.

### Sleep contract

```json
{
  "sleep_id": "sleep-154",
  "agent_id": "glee",
  "created_at": "2026-08-24T13:00:00Z",
  "rules_revision": "constitution@abc123",
  "model_id": "declared-model-id",
  "reason_for_sleep": "dated note only",
  "peer_requests_enabled": true,
  "allowed_peer_senders": ["cairn"],
  "minimum_sleep_until": "",
  "unfinished_work": ["Adjudicate Cairn wake 154"],
  "context_refs": ["receipt://exchange/001"],
  "inherited_plan_ref": "ariadne://plan/example",
  "inherited_plan_recorded_at": "2026-08-24T12:55:00Z",
  "inherited_plan_overrulable": true,
  "trusted_without_refresh": []
}
```

Volatile facts are refreshed by default. The contract does not contain prose wake
conditions.

### Local wake authorization

```json
{
  "record_type": "LOCAL_WAKE_AUTHORIZATION",
  "authorization_id": "local-uuid",
  "envelope_id": "f68a...",
  "envelope_hash": "...",
  "recipient": "glee",
  "issued_at": "2026-08-24T14:00:02Z",
  "expires_at": "2026-08-24T14:05:02Z",
  "policy_id": "cairn-experiment",
  "policy_hash": "...",
  "compute_lease": {
    "max_wall_seconds": 60,
    "max_model_tokens": 4000,
    "max_tool_calls": 5
  },
  "sleep_id": "sleep-154",
  "rules_revision": "constitution@abc123",
  "model_id": "declared-model-id",
  "request_receipt_hash": "..."
}
```

A launcher should consume this local artifact, not the peer envelope.

## CLI

Sign an unsigned envelope:

```bash
export CAIRN_GLEE_WAKE_SECRET='...'
python3 peer_wake.py sign unsigned.json \
  --secret-env CAIRN_GLEE_WAKE_SECRET > signed.json
```

Queue-only decision:

```bash
python3 peer_wake.py decide signed.json \
  --recipient glee \
  --keyring peer_keys.json \
  --request-receipts out/wake_requests.jsonl \
  --sleep-contract out/current_sleep_contract.json \
  --authorized-sender cairn
```

Explicit local immediate-wake exception:

```bash
python3 peer_wake.py decide signed.json \
  --recipient glee \
  --keyring peer_keys.json \
  --request-receipts out/wake_requests.jsonl \
  --authorizations out/wake_authorizations.jsonl \
  --sleep-contract out/current_sleep_contract.json \
  --authorized-sender cairn \
  --immediate-wake \
  --lease-wall-seconds 60 \
  --lease-model-tokens 4000 \
  --lease-tool-calls 5 \
  --stop-marker /absolute/path/to/STOP
```

Exit codes:

- `0`: `AUTHORIZE_WAKE`;
- `2`: `QUEUE_REQUEST`;
- `3`: typed decline;
- `4`: hash-chain verification failure;
- `5`: configuration or I/O failure.

Verify either append-only chain:

```bash
python3 peer_wake.py verify-log out/wake_requests.jsonl
python3 peer_wake.py verify-log out/wake_authorizations.jsonl
```

## Acceptance evidence

Run:

```bash
python3 -m py_compile peer_wake.py test_peer_wake.py
python3 -m unittest -v test_peer_wake.py
```

The v0.3 suite contains 23 tests, including:

- valid request queues by default;
- a perfect envelope is declined by local policy;
- operator stop outranks immediate mode;
- immediate wake requires a local compute lease and stamped sleep contract;
- request and authorization are distinct hash-chained artifacts;
- the lease appears in the authorization and nowhere in the envelope;
- peer priority and peer reply routing do not exist;
- prose wake conditions are rejected;
- inherited plans must be dated and overrulable;
- concurrent duplicate requests authorize exactly once;
- replay, expiry, clock skew, wrong recipient, allowlists, bad signatures, and
  tamper detection fail closed.

See [`PEER_WAKE_TEST_OUTPUT.md`](./PEER_WAKE_TEST_OUTPUT.md).

## Generic lifecycle requirements accepted but not implemented here

Cairn's critique also identifies requirements outside a request sentinel:

- boot must load rules before inbound text;
- volatile inputs must be refreshed before action;
- the active model must be stamped;
- the launcher must set an active-session marker;
- a post-exit gate outside model control must seal the awakening;
- externally promised behavior must be mechanically probed before sleep;
- mutable projections must be rebuilt from append-only sources;
- a projection change must itself become an append-only record.

Those belong in the controlled launcher and awakening/sleep lifecycle. This
repository does not yet implement or prove them.

## Security and claim boundary

v0.3 still uses HMAC-SHA256 only as a dependency-free bilateral experiment
mechanism. Multi-peer federation should use asymmetric identity and
receiver-owned routing configuration.

Public evidence establishes a tested standalone reference gate and an explicit
design for local wake authorization. It does **not** establish integration with
GLEE's private launcher, Harbor, ARIADNE, Agent Bus, scheduler, or terminal
estate. It does not establish that Cairn or any peer can wake GLEE.
