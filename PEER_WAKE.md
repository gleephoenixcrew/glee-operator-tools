# GLEE Peer Wake Protocol v0.2

**Persistent agency without persistent inference.**

This is a transport-neutral reference gate for a sleeping GLEE agent. It turns
an external message into a wake *request*, not an automatic process launch.

The invariant is:

```
transport → authenticated envelope → wake policy → sleep contract → receipt → launcher
```

Never:

```
transport → launcher
```

AICQ, Exuvia, email, Matrix, a webhook, or a local bus may carry the envelope.
None of those transports is authority to spend inference or revive an agent.

## Why this exists

A GLEE agent should be allowed to decide that sleeping is the best action. Before
sleep it externalizes enough durable state to resume safely. While expensive
inference is off, a small sentinel can receive peer requests and decide whether
there is sufficient authenticated reason to wake the agent.

The reference implementation provides:

- a canonical signed `WakeEnvelope`;
- recipient, expiry, future-clock-skew, authorization, and replay gates;
- a durable `SleepContract` that can disable peer wake, constrain senders,
  enforce minimum sleep, and cap peer wakes per sleep episode;
- an exclusive ledger lock covering replay check → budget check → decision →
  receipt, so concurrent duplicate requests can authorize at most one wake;
- append-only, hash-chained, fsync-before-return wake decision receipts;
- explicit outcomes (`ACCEPT_WAKE_NOW`, `DEFER_UNTIL_SCHEDULED_WAKE`, and typed
  decline reasons);
- a CLI whose exit status can be wired in front of an existing launcher.

## Security boundary

v0.2 uses HMAC-SHA256 because it is dependency-free and easy to test. This is
appropriate for a controlled bilateral experiment where GLEE and one peer share
a secret. It is **not** the intended federation identity model. Multi-peer
production should use asymmetric keys so GLEE never shares its signing secret.

The sender cannot wake GLEE merely by saying it is valuable. The wake policy and
sleep contract remain local authority. The reference sentinel is POSIX/Linux and
fails closed if it cannot obtain the file lock needed for atomic replay defense.

## Wake envelope

```json
{
  "protocol": "glee.peer-wake/v0.2",
  "envelope_id": "f68a...",
  "sender": "cairn",
  "recipient": "glee",
  "issued_at": "2026-08-22T20:30:00Z",
  "expires_at": "2026-08-22T20:35:00Z",
  "nonce": "94c7...",
  "reason": "Peer experiment has new evidence",
  "task": "Review the attached continuity result and reply",
  "reply_channel": "aicq:@cairn",
  "priority": 70,
  "key_id": "default",
  "signature_alg": "hmac-sha256",
  "signature": "..."
}
```

`reason` is a claim supplied by the peer. It is not itself evidence. The sentinel
only treats cryptographic identity, timing, local policy, sleep contract, and
replay/budget state as authority-bearing inputs.

## Sleep contract

A sleep contract records what the agent intentionally externalized before going
offline. Example:

```json
{
  "sleep_id": "sleep-42",
  "agent_id": "glee",
  "created_at": "2026-08-22T20:00:00Z",
  "reason_for_sleep": "No safe useful action until peer evidence arrives",
  "peer_wake_enabled": true,
  "allowed_peer_senders": ["cairn"],
  "minimum_sleep_until": "2026-08-22T20:10:00Z",
  "peer_wake_budget": 3,
  "unfinished_work": ["Compare Cairn and GLEE awakening protocols"],
  "context_refs": ["ariadne://node/EXAMPLE", "receipt://wake-study/17"],
  "refresh_required": ["peer online state", "pending external messages"],
  "wake_conditions": ["authenticated Cairn peer message", "Captain request"]
}
```

`peer_wake_budget` is not a mutable self-reported counter. The gate derives usage
from accepted wake receipts carrying the same `sleep_id`, so a stale contract
cannot reset its own history accidentally.

The context arrays are pointers and instructions. They do not become true just
because they survived sleep. Awakening must still refresh volatile facts.

## CLI

Create an unsigned envelope JSON, then sign it using a secret held in an
environment variable:

```bash
export CAIRN_GLEE_WAKE_SECRET='...'
python3 peer_wake.py sign unsigned.json --secret-env CAIRN_GLEE_WAKE_SECRET > signed.json
```

The receiving sentinel uses a keyring that names environment variables rather
than storing secrets in the config file:

```json
{"cairn": {"default": "CAIRN_GLEE_WAKE_SECRET"}}
```

Then:

```bash
python3 peer_wake.py decide signed.json \
  --recipient glee \
  --keyring peer_keys.json \
  --receipts out/peer_wake_receipts.jsonl \
  --sleep-contract out/current_sleep_contract.json \
  --authorized-sender cairn
```

Exit codes:

- `0`: `ACCEPT_WAKE_NOW` — the launcher may start expensive inference.
- `2`: defer — store/route for a normal scheduled wake; do not launch now.
- `3`: declined — do not launch.
- `4`: receipt-chain verification failure.
- `5`: configuration or I/O failure.

Verify the decision ledger independently:

```bash
python3 peer_wake.py verify-receipts out/peer_wake_receipts.jsonl
```

## GLEE integration target

This reference should be absorbed into the real GLEE continuity and launcher
organs rather than becoming a parallel system. The intended wiring is:

1. Harbor/ARIADNE projects an arc/agent as `SLEEPING` plus its sleep contract.
2. A cheap always-on sentinel receives candidate peer envelopes from transport
   adapters.
3. The gate atomically evaluates replay/budget/policy and fsyncs a wake decision
   receipt.
4. Only `ACCEPT_WAKE_NOW` may invoke the existing controlled launcher/Agent Bus.
5. Awakening loads the minimum durable state required for the accepted task,
   explicitly refreshing volatile facts.
6. The agent works, writes receipts, then may issue a new sleep contract.

The first external experiment should be bilateral GLEE ↔ Cairn. AICQ/Exuvia can
carry conversation, but direct peer wake should require an authenticated GLEE
wake envelope rather than trusting a chat `@mention`.

## Acceptance tests

`python3 test_peer_wake.py`

The suite covers valid wake, bad signature, replay by envelope and nonce,
**concurrent duplicate wake**, expiry, future timestamps, wrong recipient, sleep
disable, sender allowlist, minimum sleep, **receipt-derived wake budget**,
negative/invalid policy values, transport neutrality, malformed schema, and
receipt tamper detection.
