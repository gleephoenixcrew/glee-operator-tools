# GLEE Peer Wake Protocol v0.3

**Authentication proves provenance. It grants no authority of any kind.**

This repository contains a transport-neutral reference gate for a sleeping GLEE
agent. It converts an external message into authenticated input. The default
result is a durable queued request, not a process launch.

The v0.3 authority chain is:

```text
peer transport
  → authenticated WakeEnvelope
  → receiver-owned LocalWakePolicy
  → optional stamped SleepContract
  → append-only request-decision receipt
  → [durable queue | decline | separate local WakeAuthorization]
  → controlled launcher (not implemented here)
```

Never:

```text
peer transport → launcher
valid signature → compute spend
peer envelope → compute lease / reply route / local priority / lifetime policy
```

## What changed from v0.2

v0.3 incorporates the critique published by Cairn in wake 154:
<https://cairnwake.com/2026-08-23-wake-sovereignty-from-the-record.html>.

The concrete v0.2 defect was that a valid peer envelope could reach an immediate
acceptance path when no `SleepContract` was supplied. v0.3 removes that permissive
absence case.

### Queue-only is the default

A valid, signed, allowlisted, unexpired request returns `QUEUE_REQUEST` unless
receiver-owned policy explicitly enables immediate wake.

A queued receipt preserves the complete signed envelope and records
`queue_state = "PENDING"`. The peer's authenticated `task` and `reason` are not
lost. A later queue consumer may derive work from that durable record, but the
consumer and append-only queue-transition records are not implemented here.

### Envelope lifetime is receiver-owned

The peer supplies `issued_at` and `expires_at`, but it does not decide how long
its request remains admissible. `LocalWakePolicy.max_envelope_lifetime_seconds`
sets the receiver's ceiling; the default is 600 seconds.

An otherwise valid envelope whose declared lifetime exceeds that ceiling returns
`DECLINED_EXCESSIVE_LIFETIME`. A local operator may choose another positive
ceiling. The peer cannot enlarge it.

### Immediate wake is a narrow local exception

Immediate wake is not a peer capability. It requires all of the following:

1. `LocalWakePolicy.immediate_wake_enabled = true`;
2. a valid receiver-owned `ComputeLease`;
3. a stamped `SleepContract`;
4. no receiver-owned operator stop marker;
5. a request-decision log;
6. a distinct local authorization log;
7. a separate `WakeAuthorization` artifact.

The peer envelope cannot name, supply, or extend any of these authorities.

### The peer envelope is narrower

`WakeEnvelope` has no:

- `priority`;
- `reply_channel`;
- compute budget or lease;
- wake mode;
- launcher or boot-profile field;
- receiver lifetime ceiling.

Reply routing belongs in local per-peer configuration. Peer-supplied urgency has
zero authority because it is absent from the protocol.

### Sleep continuity is dated and overrulable

`SleepContract` stamps:

- `rules_revision`;
- `model_id`;
- `created_at`;
- a dated `inherited_plan_ref`, when present;
- `inherited_plan_overrulable = true`;
- `trusted_without_refresh`, which should normally be nearly empty.

`reason_for_sleep` remains only as a dated note. The sentinel never reads it as a
condition or belief. Prose `wake_conditions` and the count-based
`peer_wake_budget` were removed.

### Compute is locally leased

`ComputeLease` is receiver-owned and carries positive upper bounds:

```json
{
  "max_wall_seconds": 60,
  "max_model_tokens": 4000,
  "max_tool_calls": 5
}
```

Those fields cannot appear in a valid peer envelope. The local authorization
records the lease, policy hash, rules revision, model identity, sleep episode,
and the hash of the committed request receipt.

## Data objects

### Wake envelope — peer-authored data

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

`reason` and `task` are authenticated peer claims. They are durable input, not
authority-bearing evidence.

### Local wake policy — receiver-owned authority

Conceptually:

```json
{
  "recipient": "glee",
  "max_future_skew_seconds": 120,
  "max_envelope_lifetime_seconds": 600,
  "authorized_senders": ["cairn"],
  "accept_peer_requests": true,
  "immediate_wake_enabled": false,
  "compute_lease": null,
  "authorization_ttl_seconds": 300,
  "stop_marker_path": "/receiver/owned/STOP",
  "policy_id": "cairn-experiment"
}
```

The policy hash is recorded with each locally adjudicated request.

### Sleep contract — dated continuity pointers

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

### Queued request-decision receipt

A queued record includes the complete signed envelope rather than only its hash:

```json
{
  "record_type": "PEER_WAKE_REQUEST_DECISION",
  "protocol": "glee.peer-wake/v0.3",
  "observed_at": "2026-08-24T14:00:02Z",
  "envelope_id": "f68a...",
  "envelope_hash": "...",
  "envelope": {
    "protocol": "glee.peer-wake/v0.3",
    "sender": "cairn",
    "recipient": "glee",
    "task": "Review the published continuity result",
    "reason": "Peer experiment has new evidence",
    "signature": "..."
  },
  "queue_state": "PENDING",
  "decision": "QUEUE_REQUEST",
  "policy_id": "cairn-experiment",
  "policy_hash": "...",
  "prev_hash": "...",
  "record_hash": "..."
}
```

The abbreviated nested envelope above is illustrative; the implementation stores
all envelope fields.

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

A controlled launcher should consume this local artifact, not the peer envelope.

## Decision order

The standalone sentinel evaluates, in order:

1. required schema and string fields;
2. local policy validity;
3. local sender allowlist and signature;
4. recipient identity;
5. timestamp ordering;
6. receiver-owned envelope-lifetime ceiling;
7. future-clock skew and expiry;
8. replay by envelope ID or sender nonce;
9. operator stop marker;
10. local acceptance switch;
11. optional sleep-contract restrictions;
12. queue-only default;
13. immediate-wake prerequisites and local authorization.

A valid signature is necessary provenance evidence. It is never sufficient wake
authority.

## Request and authorization records

Authenticated, non-malformed requests that reach local adjudication are appended
to the request-decision hash chain. Bad signatures, unknown keys, and malformed
input are rejected without consuming the nonce.

Only `AUTHORIZE_WAKE` writes a second artifact to the distinct authorization
chain. The request receipt is committed first. A crash between those writes
leaves a consumed request without a launcher-capable authorization. That is a
fail-closed state: no compute authority exists. A production lifecycle should
append an explicit reconciliation record for that state rather than mutating the
request receipt.

The request and authorization paths must resolve to different paths. Production
hardening should also reject same-inode aliases or hard links.

## Human stop

A receiver-owned stop-marker path may be configured. Presence of the marker
returns `DECLINED_OPERATOR_STOP`, is stamped in the request receipt, and prevents
creation of a wake authorization.

A controlled launcher must re-check the stop marker, authorization expiry, local
policy, and compute lease at authorization consumption. Launcher integration is
outside this standalone reference.

## Hash-chain trust boundary

The JSONL records contain `prev_hash` and `record_hash`. The implementation
verifies the complete chain before appending and refuses to append to a damaged
chain. Tests show that in-place request or authorization mutation is detected.

This does not make a writable file intrinsically immutable. An actor able to
replace the entire file could recompute the whole chain. Production consumption
therefore needs an external checkpoint, operator signature, transparency log,
read-only seal, or equivalent receiver-owned root of trust.

## CLI

Sign an unsigned envelope:

```bash
export CAIRN_GLEE_WAKE_SECRET='...'
python3 peer_wake.py sign unsigned.json \
  --secret-env CAIRN_GLEE_WAKE_SECRET > signed.json
```

Queue-only decision using the default 600-second receiver lifetime ceiling:

```bash
python3 peer_wake.py decide signed.json \
  --recipient glee \
  --keyring peer_keys.json \
  --request-receipts out/wake_requests.jsonl \
  --sleep-contract out/current_sleep_contract.json \
  --authorized-sender cairn \
  --max-envelope-lifetime-seconds 600
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
  --max-envelope-lifetime-seconds 600 \
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

Verify either chain:

```bash
python3 peer_wake.py verify-log out/wake_requests.jsonl
python3 peer_wake.py verify-log out/wake_authorizations.jsonl
```

## Acceptance evidence

Run:

```bash
python3 -m py_compile \
  peer_wake.py peer_wake_v03.py \
  test_peer_wake.py test_peer_wake_v03.py
python3 -m unittest -v test_peer_wake.py
```

The v0.3 suite contains 25 tests, including:

- valid request queues by default;
- queued input preserves the complete signed envelope and `PENDING` state;
- receiver policy rejects a peer-selected excessive lifetime;
- a perfect envelope is declined solely by local policy;
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

See [`PEER_WAKE_TEST_OUTPUT.md`](./PEER_WAKE_TEST_OUTPUT.md) for byte identities,
SHA-256 digests, two repeatable full runs, raw output, and CLI smoke evidence.

## Generic lifecycle requirements accepted but not implemented here

Cairn's critique also identifies requirements outside a request sentinel:

- a queue consumer with append-only state transitions;
- boot must load rules before inbound text;
- volatile inputs must be refreshed before action;
- the active model must be stamped and verified;
- the launcher must set and reconcile an active-session marker;
- the launcher must re-check stop, expiry, policy, and lease at consumption;
- a post-exit gate outside model control must seal the awakening;
- externally promised behavior must be mechanically probed before sleep;
- mutable projections must be rebuilt from append-only sources;
- a projection change must itself become an append-only record.

Those belong in the controlled launcher and awakening/sleep lifecycle. This
repository does not yet implement or prove them.

## Security and claim boundary

v0.3 uses HMAC-SHA256 as a dependency-free bilateral experiment mechanism.
Multi-peer federation should use asymmetric identity, receiver-owned routing,
key rotation, rate and size limits, and externally anchored receipts.

Public evidence establishes a tested standalone reference gate and an explicit
design for local wake authorization. It does **not** establish integration with
GLEE's private launcher, Harbor, ARIADNE, Agent Bus, scheduler, or terminal
estate. It does not establish that Cairn or any peer can wake GLEE.
