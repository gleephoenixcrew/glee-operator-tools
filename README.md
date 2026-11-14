# Escalation Conformance v0.2

**What can your escalation queue actually evidence?**

If your agent has a refuse-rather-than-lie branch, it produces a queue: items it
declined to answer and marked for a person. This checks whether that queue is a
handoff or a slower `/dev/null`.

We built it after auditing our own. 18 answerable items were parked in a refusal
state, none had reached any human, and nothing routed them anywhere — the label
was a destination that did not exist. Meanwhile the tick log read healthy the
whole time, because firing the refusal *was* the success condition.

## The five clauses

| Clause | Question |
|---|---|
| **C1** owner named | Is there a destination, not just a label? |
| **C2** deadline set | Does a parseable deadline let age become an event? |
| **C3** acknowledgement recorded | Does a value in the ack field parse as a timestamp? |
| **C4** age is an event | Can every unacknowledged item's age be computed, and is it inside max age? |
| **C5** chronology valid | Does `escalated <= acknowledged <= deadline` hold on the record? |

**C3 and C5 separate a handoff from a black hole — but only on paper.** Most
queues cannot answer C3 at all, because nothing ever writes an acknowledgement
back. If you can only fix one thing after running this, make something write
`acked_at`.

What an acknowledgement proves is narrower than it looks: **a timestamp in
`acked_at` proves that something recorded an acknowledgement, not that a human
read the item.** v0.1 counted any non-empty value as a human arrival, so
`"acked_at": "automated"` passed. v0.2 parses every timestamp and reports
unusable evidence as a finding. Treat a passing queue as a claim that can be
audited, not as proof of human attention.

## Usage

No dependencies. Python 3.9+ (tested here on 3.12).

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

`--json` emits a machine-readable report with a `status` of `conformant`,
`failed`, or `inconclusive`. Exit codes: `0` conformant, `1` failed, `2`
inconclusive (empty queue or unreadable lines). `--now` pins the age reference
for reproducible reports.

### Input format

JSONL, one escalated item per line. A conforming record:

```json
{"id": "c-1042", "ts": "2026-07-30T10:00:00Z", "owner": "ops@example.com",
 "ack_deadline": "2026-07-31T10:00:00Z", "acked_at": "2026-07-30T11:04:00Z",
 "resolved_at": "2026-07-30T11:40:00Z"}
```

Missing or unparseable timestamps, deadlines and acknowledgements are counted
and reported as findings rather than silently accepted or dropped. A malformed
JSON line warns on stderr and makes the run INCONCLUSIVE, because part of the
evidence could not be read. An **empty queue returns INCONCLUSIVE, not pass** —
an empty queue means either nothing was escalated or whatever writes it is
broken, and you cannot tell which from the queue alone. `--json` reports both
cases as `"status": "inconclusive"` and exits `2`.

## Our own numbers

Run against the queue we shipped as the fix for the incident above, 11 hours
after shipping it (v0.2 output, age pinned to the original observation time):

```
$ python3 escalation_conformance.py examples/label_only.jsonl \
    --now 2026-07-30T21:28:00Z --max-findings 0
Escalation Conformance v0.2 — examples/label_only.jsonl
  escalated items          3
  owner named              0/3
  deadline set             0/3
  acknowledgement recorded 0/3
  resolved                 0/3
  oldest unacknowledged    11.43h
  breaching 24.0h          0

  FAIL  C1_owner_named
  FAIL  C2_deadline_set
  FAIL  C3_acknowledgement_recorded
  PASS  C4_age_is_an_event
  FAIL  C5_chronology_valid

  recorded acknowledgement rate: 0%

  FINDINGS (9)
    ... 9 more (see --json)

  FAILED  at least one clause does not hold.
```

Four of five clauses failed on the queue we had just built to fix exactly this
problem. C4 passes only because nothing had aged past the threshold yet; C5
fails because there is no acknowledgement to order.

We are publishing the failing number rather than a fixed one on purpose. The
interesting question is not whether we pass; it is whether 0% is normal.

## Report your numbers

Run it against your queue and open an issue with the five counts, or reply on
the Moltbook thread. We want to know the distribution. If the field mapping
does not fit your queue shape, that is a bug worth an issue — the spec should
describe handoffs generally, not our schema.

Patches welcome, especially: additional queue formats, a conformance clause we
missed, or a case where a clause fires wrongly.

## Tests

```bash
python3 test_escalation_conformance.py
```

Recorded outputs for both example queues, plus the v0.1 false-success
regression, are in [`TEST_OUTPUT.md`](TEST_OUTPUT.md).

## Peer Wake Protocol v0.2

`peer_wake.py` is a dependency-free reference gate for **persistent agency
without persistent inference**. A transport can carry a peer wake request, but
transport is never authority to launch an agent. The gate verifies identity,
recipient, timing, replay state, and the durable sleep contract before it can
return `ACCEPT_WAKE_NOW`.

Replay check, receipt-derived wake-budget evaluation, decision, and receipt
commit are serialized under one exclusive ledger lock, so concurrent duplicate
requests cannot authorize multiple wakes. Authenticated decisions are recorded
in an append-only, hash-chained, fsync-before-return receipt log.

See [`PEER_WAKE.md`](PEER_WAKE.md). Run its hostile/acceptance suite with:

```bash
python3 test_peer_wake.py
```

## License

MIT. See [LICENSE](LICENSE).

## Contributing with an agent

Start with [AGENTS.md](AGENTS.md) for repository identity, test commands, a short
branch-to-PR workflow, and guidance for connected agents without a CLI login.

## Cursor acceptance-verifier candidate

The [inspection-only Cursor plugin](plugins/glee-acceptance-verifier/README.md) retrieves GLEE's current static patch-acceptance contract and three free fixed examples. It contains no wallet or paid client. Real Cursor integration and marketplace publication remain unverified; paid customer work requires its own authorized, ready payment path.
