# Recorded test output

Everything below was produced by running the commands shown, on 2026-11-14 with
v0.2. Age-dependent examples pin the reference time with `--now
2026-07-30T21:28:00Z`, the original observation time, so the numbers are
reproducible.

## Unit + CLI tests

```
$ python3 test_escalation_conformance.py
----------------------------------------------------------------------
Ran 29 tests in 0.298s

OK
```

## examples/conforming.jsonl — all five clauses pass, exit 0

```
$ python3 escalation_conformance.py examples/conforming.jsonl --now 2026-07-30T21:28:00Z
Escalation Conformance v0.2 — examples/conforming.jsonl
  escalated items          2
  owner named              2/2
  deadline set             2/2
  acknowledgement recorded 2/2
  resolved                 2/2
  breaching 24.0h          0

  PASS  C1_owner_named
  PASS  C2_deadline_set
  PASS  C3_acknowledgement_recorded
  PASS  C4_age_is_an_event
  PASS  C5_chronology_valid

  recorded acknowledgement rate: 100%

  CONFORMANT  every clause holds on the recorded evidence.
```

JSON mode on the same file:

```
$ python3 escalation_conformance.py examples/conforming.jsonl --json --now 2026-07-30T21:28:00Z
{
  "spec_version": "0.2",
  "checked_at": "2026-07-30T21:28:00+00:00",
  "total_escalated": 2,
  "with_owner": 2,
  "with_deadline": 2,
  "with_recorded_ack": 2,
  "resolved": 2,
  "invalid_resolutions": 0,
  "oldest_unacked_hours": null,
  "breaching_max_age": 0,
  "unparseable_timestamps": 0,
  "invalid_deadlines": 0,
  "invalid_ack_values": 0,
  "late_acknowledgements": 0,
  "ack_before_escalation": 0,
  "unverifiable_chronology": 0,
  "unageable": 0,
  "future_escalations": 0,
  "findings": [],
  "recorded_ack_rate": 1.0,
  "clauses": {
    "C1_owner_named": true,
    "C2_deadline_set": true,
    "C3_acknowledgement_recorded": true,
    "C4_age_is_an_event": true,
    "C5_chronology_valid": true
  },
  "skipped_lines": 0,
  "status": "conformant",
  "queue": "examples/conforming.jsonl"
}
```

## examples/label_only.jsonl — a queue that records only that it refused

This is the shape our own queue had: a timestamp and a reason, no owner, no
deadline, no acknowledgement. It is the default shape, and it fails four of
five clauses.

```
$ python3 escalation_conformance.py examples/label_only.jsonl --now 2026-07-30T21:28:00Z
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
    c-2001 [missing evidence] owner: no owner recorded
    c-2001 [missing evidence] ack_deadline: no acknowledgement deadline recorded
    c-2001 [missing evidence] acked_at: no acknowledgement recorded
    c-2002 [missing evidence] owner: no owner recorded
    c-2002 [missing evidence] ack_deadline: no acknowledgement deadline recorded
    c-2002 [missing evidence] acked_at: no acknowledgement recorded
    c-2003 [missing evidence] owner: no owner recorded
    c-2003 [missing evidence] ack_deadline: no acknowledgement deadline recorded
    c-2003 [missing evidence] acked_at: no acknowledgement recorded

  FAILED  at least one clause does not hold.
```

## Regression — the two v0.1 false successes

Both cases were reproduced on v0.1 at commit `723a628` before the repair.

### Empty queue in JSON mode

v0.1 exited `0` with `"clauses": {}` and no indication that nothing had been
audited. An automated caller could read that as success. v0.2 exits `2`:

```
$ : > /tmp/empty.jsonl
$ python3 escalation_conformance.py /tmp/empty.jsonl --json --now 2026-07-30T21:28:00Z
{
  "spec_version": "0.2",
  "checked_at": "2026-07-30T21:28:00+00:00",
  "total_escalated": 0,
  "with_owner": 0,
  "with_deadline": 0,
  "with_recorded_ack": 0,
  "resolved": 0,
  "invalid_resolutions": 0,
  "oldest_unacked_hours": null,
  "breaching_max_age": 0,
  "unparseable_timestamps": 0,
  "invalid_deadlines": 0,
  "invalid_ack_values": 0,
  "late_acknowledgements": 0,
  "ack_before_escalation": 0,
  "unverifiable_chronology": 0,
  "unageable": 0,
  "future_escalations": 0,
  "findings": [],
  "recorded_ack_rate": null,
  "clauses": {},
  "skipped_lines": 0,
  "status": "inconclusive",
  "queue": "/tmp/empty.jsonl"
}
$ echo $?
2
```

### Populated fields that are not evidence

A record with an invalid timestamp, `"ack_deadline": "eventually"` and
`"acked_at": "automated"` passed all four v0.1 clauses and reported a 100%
human arrival rate. v0.2 treats each value as unusable evidence and exits `1`:

```
$ cat /tmp/bad.jsonl
{"id":"t-1","ts":"not-a-date","owner":"alice","ack_deadline":"eventually","acked_at":"automated"}
$ python3 escalation_conformance.py /tmp/bad.jsonl --now 2026-07-30T21:28:00Z
Escalation Conformance v0.2 — /tmp/bad.jsonl
  escalated items          1
  owner named              1/1
  deadline set             0/1
  acknowledgement recorded 0/1
  resolved                 0/1
  breaching 24.0h          0
  unusable timestamps      1
  invalid deadlines        1
  invalid acknowledgements 1
  unageable items          1

  PASS  C1_owner_named
  FAIL  C2_deadline_set
  FAIL  C3_acknowledgement_recorded
  FAIL  C4_age_is_an_event
  FAIL  C5_chronology_valid

  recorded acknowledgement rate: 0%

  FINDINGS (3)
    t-1 [invalid evidence] ack_deadline: 'eventually' is not an ISO-8601 timestamp
    t-1 [invalid evidence] ts: 'not-a-date' is not an ISO-8601 timestamp
    t-1 [invalid evidence] acked_at: 'automated' is not an ISO-8601 timestamp; presence alone is not acknowledgement

  FAILED  at least one clause does not hold.
```
