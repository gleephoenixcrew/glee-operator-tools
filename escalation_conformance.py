#!/usr/bin/env python3
"""Escalation Conformance v0.2 — what can this queue actually evidence?

A refusal state is a measurement, not a handoff. This inspects an escalation
queue (JSONL, one record per escalated item) and asks five questions:

  1. Does each record name an owner — a destination, not just a label?
  2. Does each record carry a parseable deadline, so age can become an event?
  3. Does each record carry a recorded acknowledgement that parses as a
     timestamp?
  4. Can every unacknowledged item's age be computed, and is it within max age?
  5. Does the recorded order hold: escalated <= acknowledged <= deadline?

An acknowledgement timestamp proves that something wrote a timestamp into the
ack field. It does not prove that a human read the item, and this checker does
not claim it does. Presence alone is not evidence: "automated" in an ack field
is a finding, not a handoff.

Dependency-free on purpose: any operator can run this against their own queue.
Field names are configurable because every estate spells them differently.

    python3 escalation_conformance.py QUEUE.jsonl
    python3 escalation_conformance.py QUEUE.jsonl --ack-field handled_at \
        --owner-field assignee --max-age-hours 24

Exit codes: 0 conformant, 1 failed, 2 inconclusive (empty queue or unreadable
lines). The JSON report carries the same verdict in `status`.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

SPEC_VERSION = "0.2"
EXIT_CONFORMANT = 0
EXIT_FAILED = 1
EXIT_INCONCLUSIVE = 2

KIND_FAILURE = "failure"
KIND_MISSING = "missing_evidence"
KIND_INVALID = "invalid_evidence"


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
    """Return (records, skipped). Non-object or malformed lines are skipped."""
    records = []
    skipped = 0
    with open(path, encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                print(f"warning: {path}:{line_no} is not valid JSON, skipped",
                      file=sys.stderr)
                skipped += 1
                continue
            if not isinstance(record, dict):
                print(f"warning: {path}:{line_no} is not a JSON object, skipped",
                      file=sys.stderr)
                skipped += 1
                continue
            records.append(record)
    return records, skipped


def present(record, field):
    """A field counts as present only if it holds a non-empty value."""
    value = record.get(field)
    if value is None or value is False:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    return True


def record_label(record, fields, line_no):
    """Prefer the record's own id; fall back to its line number."""
    value = record.get(fields["id"])
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return f"line {line_no}"


def add_finding(findings, record_id, line_no, code, kind, field, detail):
    findings.append({
        "record_id": record_id,
        "line": line_no,
        "code": code,
        "kind": kind,
        "field": field,
        "detail": detail,
    })


def audit(records, fields, max_age_hours, now):
    total = len(records)
    result = {
        "spec_version": SPEC_VERSION,
        "checked_at": now.isoformat(),
        "total_escalated": total,
        "with_owner": 0,
        "with_deadline": 0,
        "with_recorded_ack": 0,
        "resolved": 0,
        "invalid_resolutions": 0,
        "oldest_unacked_hours": None,
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
    }
    findings = result["findings"]
    oldest = None

    for line_no, record in enumerate(records, 1):
        rid = record_label(record, fields, line_no)

        if present(record, fields["owner"]):
            result["with_owner"] += 1
        else:
            add_finding(findings, rid, line_no, "missing_owner", KIND_MISSING,
                        fields["owner"], "no owner recorded")

        deadline = parse_ts(record.get(fields["deadline"]))
        if deadline is not None:
            result["with_deadline"] += 1
        elif present(record, fields["deadline"]):
            result["invalid_deadlines"] += 1
            add_finding(findings, rid, line_no, "invalid_deadline", KIND_INVALID,
                        fields["deadline"],
                        f"{record.get(fields['deadline'])!r} is not an "
                        "ISO-8601 timestamp")
        else:
            add_finding(findings, rid, line_no, "missing_deadline", KIND_MISSING,
                        fields["deadline"],
                        "no acknowledgement deadline recorded")

        escalated = parse_ts(record.get(fields["escalated"]))
        if escalated is None:
            result["unparseable_timestamps"] += 1
            if present(record, fields["escalated"]):
                add_finding(findings, rid, line_no, "invalid_timestamp",
                            KIND_INVALID, fields["escalated"],
                            f"{record.get(fields['escalated'])!r} is not an "
                            "ISO-8601 timestamp")
            else:
                add_finding(findings, rid, line_no, "missing_timestamp",
                            KIND_MISSING, fields["escalated"],
                            "no escalation timestamp recorded")

        ack = parse_ts(record.get(fields["ack"]))
        if ack is not None:
            result["with_recorded_ack"] += 1
        elif present(record, fields["ack"]):
            result["invalid_ack_values"] += 1
            add_finding(findings, rid, line_no, "invalid_ack", KIND_INVALID,
                        fields["ack"],
                        f"{record.get(fields['ack'])!r} is not an ISO-8601 "
                        "timestamp; presence alone is not acknowledgement")
        else:
            add_finding(findings, rid, line_no, "missing_ack", KIND_MISSING,
                        fields["ack"], "no acknowledgement recorded")

        if parse_ts(record.get(fields["resolved"])) is not None:
            result["resolved"] += 1
        elif present(record, fields["resolved"]):
            result["invalid_resolutions"] += 1

        if ack is not None:
            if deadline is not None and ack > deadline:
                result["late_acknowledgements"] += 1
                late_hours = round(
                    (ack - deadline).total_seconds() / 3600.0, 2)
                add_finding(findings, rid, line_no, "ack_after_deadline",
                            KIND_FAILURE, fields["ack"],
                            f"acknowledged {late_hours}h after the recorded "
                            "deadline")
            if escalated is not None and ack < escalated:
                result["ack_before_escalation"] += 1
                add_finding(findings, rid, line_no, "ack_before_escalation",
                            KIND_FAILURE, fields["ack"],
                            "acknowledgement precedes the escalation timestamp")
            if escalated is None or deadline is None:
                result["unverifiable_chronology"] += 1
                add_finding(findings, rid, line_no, "chronology_unverifiable",
                            KIND_MISSING, fields["ack"],
                            "acknowledgement cannot be ordered against a "
                            "readable escalation timestamp and deadline")

        if ack is None:
            if escalated is None:
                result["unageable"] += 1
            elif escalated > now:
                result["future_escalations"] += 1
                result["unageable"] += 1
                add_finding(findings, rid, line_no, "future_escalation",
                            KIND_INVALID, fields["escalated"],
                            "escalation timestamp is in the future; age cannot "
                            "be measured")
            else:
                age_hours = (now - escalated).total_seconds() / 3600.0
                if oldest is None or age_hours > oldest:
                    oldest = age_hours
                if age_hours > max_age_hours:
                    result["breaching_max_age"] += 1
                    add_finding(findings, rid, line_no,
                                "unacknowledged_overdue", KIND_FAILURE,
                                fields["escalated"],
                                f"unacknowledged for {round(age_hours, 2)}h "
                                f"(max {max_age_hours}h)")

    if oldest is not None:
        result["oldest_unacked_hours"] = round(oldest, 2)
    result["recorded_ack_rate"] = (
        round(result["with_recorded_ack"] / total, 4) if total else None
    )
    return result


def conformance(result):
    """Five independent clauses. C3 is about recorded evidence, not people."""
    total = result["total_escalated"]
    if not total:
        return {}
    return {
        "C1_owner_named": result["with_owner"] == total,
        "C2_deadline_set": result["with_deadline"] == total,
        "C3_acknowledgement_recorded": result["with_recorded_ack"] == total,
        "C4_age_is_an_event": (
            result["breaching_max_age"] == 0 and result["unageable"] == 0
        ),
        "C5_chronology_valid": (
            result["with_recorded_ack"] == total
            and result["late_acknowledgements"] == 0
            and result["ack_before_escalation"] == 0
            and result["unverifiable_chronology"] == 0
        ),
    }


def verdict(result, skipped_lines=0):
    """Failed beats inconclusive: proof of a break does not need all lines."""
    clauses = result.get("clauses") or {}
    if clauses and not all(clauses.values()):
        return "failed"
    if not clauses or skipped_lines:
        return "inconclusive"
    return "conformant"


def exit_code(status):
    return {
        "conformant": EXIT_CONFORMANT,
        "failed": EXIT_FAILED,
        "inconclusive": EXIT_INCONCLUSIVE,
    }[status]


def render(result, path, max_age_hours, max_findings):
    total = result["total_escalated"]
    print(f"Escalation Conformance v{SPEC_VERSION} — {path}")
    print(f"  {'escalated items':<25}{total}")
    print(f"  {'owner named':<25}{result['with_owner']}/{total}")
    print(f"  {'deadline set':<25}{result['with_deadline']}/{total}")
    print(f"  {'acknowledgement recorded':<25}"
          f"{result['with_recorded_ack']}/{total}")
    print(f"  {'resolved':<25}{result['resolved']}/{total}")
    if result["oldest_unacked_hours"] is not None:
        print(f"  {'oldest unacknowledged':<25}"
              f"{result['oldest_unacked_hours']}h")
    print(f"  {'breaching ' + str(max_age_hours) + 'h':<25}"
          f"{result['breaching_max_age']}")
    if result["skipped_lines"]:
        print(f"  {'unreadable lines':<25}{result['skipped_lines']}")
    if result["unparseable_timestamps"]:
        print(f"  {'unusable timestamps':<25}"
              f"{result['unparseable_timestamps']}")
    if result["invalid_deadlines"]:
        print(f"  {'invalid deadlines':<25}{result['invalid_deadlines']}")
    if result["invalid_ack_values"]:
        print(f"  {'invalid acknowledgements':<25}"
              f"{result['invalid_ack_values']}")
    if result["invalid_resolutions"]:
        print(f"  {'invalid resolutions':<25}"
              f"{result['invalid_resolutions']}")
    if result["late_acknowledgements"]:
        print(f"  {'late acknowledgements':<25}"
              f"{result['late_acknowledgements']}")
    if result["ack_before_escalation"]:
        print(f"  {'ack before escalation':<25}"
              f"{result['ack_before_escalation']}")
    if result["unverifiable_chronology"]:
        print(f"  {'unverifiable chronology':<25}"
              f"{result['unverifiable_chronology']}")
    if result["unageable"]:
        print(f"  {'unageable items':<25}{result['unageable']}")
    if result["future_escalations"]:
        print(f"  {'future escalations':<25}"
              f"{result['future_escalations']}")
    print()

    for clause, passed in result["clauses"].items():
        print(f"  {'PASS' if passed else 'FAIL'}  {clause}")
    if result["clauses"]:
        rate = result["recorded_ack_rate"] or 0.0
        print(f"\n  recorded acknowledgement rate: {rate:.0%}")

    findings = result["findings"]
    shown = max(0, max_findings)
    if findings:
        print(f"\n  FINDINGS ({len(findings)})")
        for item in findings[:shown]:
            kind = item["kind"].replace("_", " ")
            print(f"    {item['record_id']} [{kind}] {item['field']}: "
                  f"{item['detail']}")
        if len(findings) > shown:
            print(f"    ... {len(findings) - shown} more (see --json)")

    print()
    status = result["status"]
    if status == "conformant":
        print("  CONFORMANT  every clause holds on the recorded evidence.")
    elif status == "failed":
        print("  FAILED  at least one clause does not hold.")
    elif not total:
        print("  INCONCLUSIVE  queue is empty — either nothing was escalated,")
        print("                or whatever writes this queue is broken.")
    else:
        print("  INCONCLUSIVE  some lines could not be read; the readable")
        print("                records pass, but the queue is not fully audited.")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Escalation Conformance v0.2 — what can this queue "
                    "actually evidence?")
    parser.add_argument("queue", help="JSONL file, one escalated item per line")
    parser.add_argument("--escalated-field", default="ts",
                        help="timestamp the item entered the queue (default: ts)")
    parser.add_argument("--owner-field", default="owner",
                        help="who must act (default: owner)")
    parser.add_argument("--deadline-field", default="ack_deadline",
                        help="when the age becomes an event (default: ack_deadline)")
    parser.add_argument("--ack-field", default="acked_at",
                        help="recorded acknowledgement timestamp (default: acked_at)")
    parser.add_argument("--resolved-field", default="resolved_at",
                        help="when the item was closed (default: resolved_at)")
    parser.add_argument("--id-field", default="id",
                        help="record identifier used in findings (default: id)")
    parser.add_argument("--max-age-hours", type=float, default=24.0,
                        help="age at which an unacknowledged item breaches (default: 24)")
    parser.add_argument("--now", default=None,
                        help="ISO-8601 reference time for age checks "
                             "(default: current UTC time)")
    parser.add_argument("--max-findings", type=int, default=20,
                        help="findings printed in text mode (default: 20)")
    parser.add_argument("--json", action="store_true", help="emit JSON only")
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc)
    if args.now is not None:
        now = parse_ts(args.now)
        if now is None:
            parser.error("--now must be an ISO-8601 timestamp")

    fields = {
        "id": args.id_field,
        "escalated": args.escalated_field,
        "owner": args.owner_field,
        "deadline": args.deadline_field,
        "ack": args.ack_field,
        "resolved": args.resolved_field,
    }

    records, skipped = load(args.queue)
    result = audit(records, fields, args.max_age_hours, now)
    result["clauses"] = conformance(result)
    result["skipped_lines"] = skipped
    result["status"] = verdict(result, skipped)
    result["queue"] = args.queue

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        render(result, args.queue, args.max_age_hours, args.max_findings)
    return exit_code(result["status"])


if __name__ == "__main__":
    raise SystemExit(main())
