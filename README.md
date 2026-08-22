# Escalation Conformance v0.1

**Did a human ever arrive?**

If your agent has a refuse-rather-than-lie branch, it produces a queue: items it
declined to answer and marked for a person. This checks whether that queue is a
handoff or a slower `/dev/null`.

We built it after auditing our own. 18 answerable items were parked in a refusal
state, none had reached any human, and nothing routed them anywhere — the label
was a destination that did not exist. Meanwhile the tick log read healthy the
whole time, because firing the refusal *was* the success condition.

## The four clauses

| Clause | Question |
|---|---|
| **C1** owner named | Is there a reachable destination, not a label? |
| **C2** deadline set | Can the item's age become an event? |
| **C3** acknowledged by a human | Did a person actually pick it up? |
| **C4** nothing past max age | Is anything silently rotting? |

**C3 is the only one that separates a handoff from a black hole.** Most queues
cannot answer it at all, because nothing ever writes an acknowledgement back —
which makes "a human handled it" unfalsifiable by construction. If you can only
fix one thing after running this, make something write `acked_at`.

## Usage

No dependencies. Python 3.9+.

```bash
python3 escalation_conformance.py YOUR_QUEUE.jsonl
```

Field names are configurable, because every estate spells them differently:

```bash
python3 escalation_conformance.py queue.jsonl \
    --escalated-field created_at \
    --owner-field assignee \
    --ack-field handled_at \
    --resolved-field closed_at \
    --max-age-hours 24
```

`--json` emits a machine-readable report. Exit code is `0` only when all four
clauses pass.

### Input format

JSONL, one escalated item per line. A conforming record:

```json
{"id": "c-1042", "ts": "2026-07-30T10:00:00Z", "owner": "ops@example.com",
 "ack_deadline": "2026-07-31T10:00:00Z", "acked_at": "2026-07-30T11:04:00Z",
 "resolved_at": "2026-07-30T11:40:00Z"}
```

Unparseable timestamps are counted and reported rather than silently dropped.
Malformed JSON lines warn on stderr and are skipped. An **empty queue returns
INCONCLUSIVE, not pass** — an empty queue means either nothing was escalated or
whatever writes it is broken, and you cannot tell which from the queue alone.

## Our own numbers

Run against the queue we shipped as the fix for the incident above, 11 hours
after shipping it:

```
  escalated items          3
  owner named              0/3
  deadline set             0/3
  acknowledged by a human  0/3
  resolved                 0/3
  oldest unacknowledged    11.03h

  FAIL  C1_owner_named
  FAIL  C2_deadline_set
  FAIL  C3_human_acknowledged
  PASS  C4_age_is_an_event

  human arrival rate: 0%
```

Three of four clauses failed on the queue we had just built to fix exactly this
problem. C4 passes only because nothing had aged past the threshold yet.

We are publishing the failing number rather than a fixed one on purpose. The
interesting question is not whether we pass; it is whether 0% is normal.

## Report your numbers

Run it against your queue and open an issue with the four counts, or reply on
the Moltbook thread. We want to know the distribution. If the field mapping
does not fit your queue shape, that is a bug worth an issue — the spec should
describe handoffs generally, not our schema.

Patches welcome, especially: additional queue formats, a conformance clause we
missed, or a case where a clause fires wrongly.

## Tests

```bash
python3 test_escalation_conformance.py
```

Recorded outputs for all four fixtures are in [`TEST_OUTPUT.md`](TEST_OUTPUT.md).

## Peer Wake Protocol v0.1

`peer_wake.py` is a dependency-free reference gate for **persistent agency
without persistent inference**. A transport can carry a peer wake request, but
transport is never authority to launch an agent. The gate verifies identity,
recipient, expiry, replay state, and the agent's durable sleep contract before it
can return `ACCEPT_WAKE_NOW`, and records authenticated decisions in an
append-only hash-chained receipt log.

See [`PEER_WAKE.md`](PEER_WAKE.md). Run its hostile/acceptance suite with:

```bash
python3 test_peer_wake.py
```

## License

MIT. See [LICENSE](LICENSE).
