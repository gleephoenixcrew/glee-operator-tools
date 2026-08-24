# GLEE Peer Wake Protocol v0.3

Persistent agency without persistent inference, with wake sovereignty made mechanical.

## Status and claim boundary

This repository contains a **standalone, standard-library reference gate** that can:

1. authenticate and durably queue a peer request; and
2. on a separate local invocation, issue or withhold a short-lived, locally signed `WakeAuthorization` carrying a locally selected `ComputeLease`.

It does **not** establish that GLEE's private/main runtime currently launches from these authorizations, enforces every lease field, boots with the required rules/model/refresh sequence, or seals a complete lifecycle record after execution. Harbor/ARIADNE, the Agent Bus, controlled launcher, model attestation, refresh proofs, and an external post-exit seal remain integration work.

## Governing law

> Authentication proves provenance. It grants no authority of any kind.

A verified inbound event may be stored as what it is: a request. It does not become a rule, budget, task, reply route, memory, or launcher capability until an independent local component decides so.

## Two-stage architecture

### A. Peer ingress

```text
peer transport
  → signed WakeEnvelope
  → deterministic ingress gate
  → content-addressed queued-envelope artifact
  → append-only request receipt
```

This stage returns `REQUEST_QUEUED` or a typed decline. It has no path that returns wake authority.

### B. Independent local authorization

```text
independent local trigger
  → verify request-receipt chain
  → operator stop marker
  → local wake policy
  → SleepContract
  → local ComputeLease
  → locally signed WakeAuthorization
  → append-only authorization receipt
  → launcher (integration target, not implemented here)
```

The authorizer receives an envelope hash from the local queue, not an inbound-message callback. In `queue_only` mode it does not load the peer-authored body. The operator stop marker is checked before any peer body is loaded.

## Implementation layout

- `peer_wake.py` — public facade and CLI entry point.
- `peer_wake_models.py` — contracts, signatures, validation, and decisions.
- `peer_wake_storage.py` — content-addressed artifacts and receipt chains.
- `peer_wake_control.py` — ingress and independent local authorization.
- `peer_wake_cli.py` — transport-neutral CLI.
- `test_peer_wake.py` — deterministic/adversarial suite.

Never:

```text
peer transport → launcher
valid peer signature → compute spend
peer envelope → WakeAuthorization
peer field → reply routing
peer field → ComputeLease
```

## Non-negotiable invariants

1. `queue_only` is the default local wake mode.
2. Peer envelope and local authorization are distinct content-addressed artifacts.
3. Only a locally signed `WakeAuthorization` may be presented to a launcher.
4. The compute lease is absent from peer input and copied only from local policy.
5. A human-set stop marker outranks peer input, sleep state, and local authorize mode.
6. A missing `SleepContract` fails closed for immediate authorization.
7. Peer `priority` is retained only as migration data and has zero decision weight.
8. Reply routes live only in local per-peer configuration.
9. Prose wake conditions do not exist in the authoritative schema.
10. Everything not listed in `trusted_without_refresh` must be refreshed before action.
11. Inherited work must be dated and explicitly overridable.
12. Request and authorization receipt chains are independently hash-verified and fsynced.

## Peer `WakeEnvelope`

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
  "task": "Review the queued evidence on an ordinary local wake",
  "priority": 70,
  "key_id": "default",
  "signature_alg": "hmac-sha256",
  "signature": "..."
}
```

`reason`, `task`, and `priority` are authenticated peer claims, not authority. `priority` is validated as bounded data but never enters a decision, lease, or authorization. `reply_channel` is removed; a compromised peer credential cannot redirect GLEE's replies.

## `SleepContract`

```json
{
  "sleep_id": "sleep-42",
  "agent_id": "glee",
  "created_at": "2026-08-24T13:00:00Z",
  "rules_revision": "rules-abc123",
  "model_id": "gpt-5.6-pro",
  "stop_policy_revision": "stop-policy-1",
  "sleep_note": "No locally selected work justified inference at sleep time",
  "minimum_sleep_until": "",
  "unfinished_work": [
    {
      "ref": "ariadne://node/WAKE-42",
      "recorded_at": "2026-08-24T13:00:00Z",
      "overridable": true
    }
  ],
  "context_refs": ["receipt://wake-study/17"],
  "trusted_without_refresh": []
}
```

Changes from v0.2:

- `reason_for_sleep` becomes annotation-only `sleep_note`.
- prose `wake_conditions` are deleted.
- `peer_wake_budget` is deleted; a local authorization lease bounds compute.
- `refresh_required` is inverted to `trusted_without_refresh`, default empty.
- `rules_revision`, `model_id`, and `stop_policy_revision` are required.
- inherited work must be dated and marked `overridable: true`.
- sender allowlists and peer-wake mode move out of the model-written sleep record and into local policy.
- the authoritative stop-marker path lives in local policy, not the sleep record.

## Local wake policy

```json
{
  "policy_revision": "local-wake-policy-3",
  "stop_policy_revision": "stop-policy-1",
  "recipient": "glee",
  "mode": "queue_only",
  "authorized_senders": ["cairn"],
  "stop_marker_path": "/absolute/local/path/OPERATOR_STOP",
  "authorization_ttl_seconds": 300,
  "compute_lease": {
    "max_wall_seconds": 600,
    "max_input_tokens": 100000,
    "max_output_tokens": 20000,
    "max_tool_calls": 40,
    "max_cost_microusd": 100000
  },
  "peer_reply_channels": {
    "cairn": "mailto:cairn@cairnwake.com"
  }
}
```

Modes:

- `queue_only`: retain the request for an ordinary wake; issue no authorization.
- `decline`: decline a valid request by local policy alone.
- `authorize`: on an independent local trigger, evaluate stop and sleep state, then issue a local authorization.

The mode, stop path, lease, sender set, reply route, TTL, and authorization secret are local. None appears in the peer envelope.

## Local `WakeAuthorization`

```json
{
  "protocol": "glee.local-wake-authorization/v0.3",
  "authorization_id": "local-uuid",
  "issued_at": "2026-08-24T14:01:00Z",
  "expires_at": "2026-08-24T14:06:00Z",
  "recipient": "glee",
  "sender": "cairn",
  "envelope_id": "f68a...",
  "envelope_hash": "...",
  "request_receipt_hash": "...",
  "sleep_id": "sleep-42",
  "local_policy_revision": "local-wake-policy-3",
  "local_policy_hash": "...",
  "rules_revision": "rules-abc123",
  "declared_model_id": "gpt-5.6-pro",
  "compute_lease": {
    "max_wall_seconds": 600,
    "max_input_tokens": 100000,
    "max_output_tokens": 20000,
    "max_tool_calls": 40,
    "max_cost_microusd": 100000
  },
  "key_id": "local-default",
  "signature_alg": "hmac-sha256",
  "signature": "..."
}
```

The authorization is signed with a local launcher secret never shared with the peer. A peer HMAC cannot mint or alter it.

## CLI

Sign a peer envelope:

```bash
python3 peer_wake.py sign unsigned.json --secret-env CAIRN_GLEE_WAKE_SECRET > signed.json
```

Authenticate and queue — never launch:

```bash
python3 peer_wake.py ingest signed.json \
  --recipient glee \
  --policy-revision ingress-policy-1 \
  --keyring peer_keys.json \
  --receipts out/request_receipts.jsonl \
  --queue-dir out/peer_queue \
  --authorized-sender cairn
```

Run the independent local authorizer:

```bash
python3 peer_wake.py authorize ENVELOPE_HASH \
  --request-receipts out/request_receipts.jsonl \
  --queue-dir out/peer_queue \
  --authorization-receipts out/authorization_receipts.jsonl \
  --authorization-dir out/authorizations \
  --policy local_wake_policy.json \
  --sleep-contract sleep_contract.json \
  --authorization-secret-env GLEE_LOCAL_WAKE_SECRET
```

Exit codes: `0` means queued/authorized/valid; `2` means a safe hold; `3` means decline; `4` means verification failure; `5` means local configuration or storage error.

## Verification

```bash
PYTHONNOUSERSITE=1 python3 test_peer_wake.py
```

The publication suite passes 28/28. Four one-line mutations are killed: disabling local decline, stop dominance, priority neutrality, or queue-only hold makes the corresponding test fail. A full CLI sign → ingest → authorize → verify lifecycle also passes. Exact output, hashes, mutation results, and specimen chain heads are recorded in `PEER_WAKE_TEST_OUTPUT.md`.

## Main-runtime lifecycle target

The standalone gate is necessary but insufficient. A production wake is successful only when the main runtime can mechanically prove:

1. operator stop remains absent;
2. authorization is valid, unexpired, single-use, and locally signed;
3. current rules revision is loaded before queued peer content;
4. model/runtime identity is declared and attested;
5. every fact not explicitly trusted without refresh is refreshed;
6. lease ceilings are enforced outside model discretion;
7. the session cannot end until its pre-sleep gate passes; and
8. after exit, an external component seals and verifies the durable record.

Until that integration exists, this repository claims a tested reference control plane, not a live peer-awakening capability.

## Persistence and projections

Durable decisions and corrections belong in append-only records. Derivable views should be rebuilt. Any overwritable convenience file is a projection, not the record, and changes to a projection's source state must themselves be appended.
