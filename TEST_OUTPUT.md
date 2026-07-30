# Recorded test output

Everything below was produced by running the commands shown, on 2026-07-30.

## Unit + CLI tests

```
$ python3 test_escalation_conformance.py
----------------------------------------------------------------------
Ran 18 tests in 0.210s

OK
```

## examples/conforming.jsonl — all clauses pass, exit 0

```
$ python3 escalation_conformance.py examples/conforming.jsonl
Escalation Conformance v0.1 — examples/conforming.jsonl
  escalated items          2
  owner named              2/2
  deadline set             2/2
  acknowledged by a human  2/2
  resolved                 2/2
  breaching 24.0h            0

  PASS  C1_owner_named
  PASS  C2_deadline_set
  PASS  C3_human_acknowledged
  PASS  C4_age_is_an_event

  human arrival rate: 100%
```

## examples/label_only.jsonl — a queue that records only that it refused

This is the shape our own queue had: a timestamp and a reason, no owner, no
deadline, no acknowledgement. It is the default shape, and it fails three of
four clauses.

```
$ python3 escalation_conformance.py examples/label_only.jsonl
Escalation Conformance v0.1 — examples/label_only.jsonl
  escalated items          3
  owner named              0/3
  deadline set             0/3
  acknowledged by a human  0/3
  resolved                 0/3
  oldest unacknowledged    11.43h
  breaching 24.0h            0

  FAIL  C1_owner_named
  FAIL  C2_deadline_set
  FAIL  C3_human_acknowledged
  PASS  C4_age_is_an_event

  human arrival rate: 0%
```

## JSON mode

```
$ python3 escalation_conformance.py examples/label_only.jsonl --json
{
  "spec_version": "0.1",
  "total_escalated": 3,
  "with_owner": 0,
  "with_deadline": 0,
  "acknowledged_by_human": 0,
  "resolved": 0,
  "oldest_unacked_hours": 11.43,
  "breaching_max_age": 0,
  "unparseable_timestamps": 0,
  "human_arrival_rate": 0.0,
  "clauses": {
    "C1_owner_named": false,
    "C2_deadline_set": false,
    "C3_human_acknowledged": false,
    "C4_age_is_an_event": true
  },
  "queue": "examples/label_only.jsonl"
}
```
