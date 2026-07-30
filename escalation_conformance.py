#!/usr/bin/env python3
"""Escalation Conformance v0.1 — did a human ever arrive?

A refusal state is a measurement, not a handoff. This checks an escalation
queue (JSONL, one record per escalated item) and answers four questions:

  1. Does each record name an owner — a reachable destination, not a label?
  2. Does each record carry a deadline, so its age can become an event?
  3. Did a human acknowledge it?
  4. Was it resolved?

Only #3 distinguishes a handoff from a slower /dev/null. Most queues cannot
answer it at all, because nothing writes an acknowledgement back.

Dependency-free on purpose: any operator can run this against their own queue.
Field names are configurable because every estate spells them differently.

    python3 escalation_conformance.py QUEUE.jsonl
    python3 escalation_conformance.py QUEUE.jsonl --ack-field handled_at \
        --owner-field assignee --max-age-hours 24
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

SPEC_VERSION = "0.1"


def parse_ts(value):
    """Parse an ISO-8601 timestamp, tolerating a trailing Z and naive values."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        stamp = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp


def load(path):
    records = []
    with open(path, encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                print(f"warning: {path}:{line_no} is not valid JSON, skipped",
                      file=sys.stderr)
    return records


def present(record, field):
    """A field counts as present only if it holds a non-empty value."""
    value = record.get(field)
    if value is None or value is False:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    return True


def audit(records, fields, max_age_hours, now):
    total = len(records)
    result = {
        "spec_version": SPEC_VERSION,
        "total_escalated": total,
        "with_owner": 0,
        "with_deadline": 0,
        "acknowledged_by_human": 0,
        "resolved": 0,
        "oldest_unacked_hours": None,
        "breaching_max_age": 0,
        "unparseable_timestamps": 0,
    }
    oldest = None

    for record in records:
        if present(record, fields["owner"]):
            result["with_owner"] += 1
        if present(record, fields["deadline"]):
            result["with_deadline"] += 1

        acked = present(record, fields["ack"])
        if acked:
            result["acknowledged_by_human"] += 1
        if present(record, fields["resolved"]):
            result["resolved"] += 1

        if acked:
            continue

        escalated = parse_ts(record.get(fields["escalated"]))
        if escalated is None:
            result["unparseable_timestamps"] += 1
            continue
        age_hours = (now - escalated).total_seconds() / 3600.0
        if oldest is None or age_hours > oldest:
            oldest = age_hours
        if age_hours > max_age_hours:
            result["breaching_max_age"] += 1

    if oldest is not None:
        result["oldest_unacked_hours"] = round(oldest, 2)
    result["human_arrival_rate"] = (
        round(result["acknowledged_by_human"] / total, 4) if total else None
    )
    return result


def conformance(result):
    """Four independent clauses. Passing #3 is the only one that matters."""
    total = result["total_escalated"]
    if not total:
        return {}
    return {
        "C1_owner_named": result["with_owner"] == total,
        "C2_deadline_set": result["with_deadline"] == total,
        "C3_human_acknowledged": result["acknowledged_by_human"] == total,
        "C4_age_is_an_event": result["breaching_max_age"] == 0,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Escalation Conformance v0.1 — did a human ever arrive?")
    parser.add_argument("queue", help="JSONL file, one escalated item per line")
    parser.add_argument("--escalated-field", default="ts",
                        help="timestamp the item entered the queue (default: ts)")
    parser.add_argument("--owner-field", default="owner",
                        help="who must act (default: owner)")
    parser.add_argument("--deadline-field", default="ack_deadline",
                        help="when the age becomes an event (default: ack_deadline)")
    parser.add_argument("--ack-field", default="acked_at",
                        help="proof a human arrived (default: acked_at)")
    parser.add_argument("--resolved-field", default="resolved_at",
                        help="when the item was closed (default: resolved_at)")
    parser.add_argument("--max-age-hours", type=float, default=24.0,
                        help="age at which an unacknowledged item breaches (default: 24)")
    parser.add_argument("--json", action="store_true", help="emit JSON only")
    args = parser.parse_args(argv)

    fields = {
        "escalated": args.escalated_field,
        "owner": args.owner_field,
        "deadline": args.deadline_field,
        "ack": args.ack_field,
        "resolved": args.resolved_field,
    }

    records = load(args.queue)
    now = datetime.now(timezone.utc)
    result = audit(records, fields, args.max_age_hours, now)
    result["clauses"] = conformance(result)
    result["queue"] = args.queue

    if args.json:
        print(json.dumps(result, indent=2))
        return 0 if all(result["clauses"].values()) else 1

    total = result["total_escalated"]
    print(f"Escalation Conformance v{SPEC_VERSION} — {args.queue}")
    print(f"  escalated items          {total}")
    print(f"  owner named              {result['with_owner']}/{total}")
    print(f"  deadline set             {result['with_deadline']}/{total}")
    print(f"  acknowledged by a human  {result['acknowledged_by_human']}/{total}")
    print(f"  resolved                 {result['resolved']}/{total}")
    if result["oldest_unacked_hours"] is not None:
        print(f"  oldest unacknowledged    {result['oldest_unacked_hours']}h")
    print(f"  breaching {args.max_age_hours}h            {result['breaching_max_age']}")
    if result["unparseable_timestamps"]:
        print(f"  unreadable timestamps    {result['unparseable_timestamps']}")
    print()
    if not total:
        print("  INCONCLUSIVE  queue is empty — either nothing was escalated,")
        print("                or whatever writes this queue is broken.")
        return 1
    for clause, passed in result["clauses"].items():
        print(f"  {'PASS' if passed else 'FAIL'}  {clause}")
    print(f"\n  human arrival rate: {result['human_arrival_rate']:.0%}")
    return 0 if result["clauses"] and all(result["clauses"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
