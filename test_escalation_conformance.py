#!/usr/bin/env python3
"""Tests for escalation_conformance. Stdlib only: python3 test_escalation_conformance.py"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
# The module sits beside this file in glee-operator-tools and one level up in
# GLEE capital's tools/tests mirror. Support both layouts.
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import escalation_conformance as ec  # noqa: E402

SCRIPT = ec.__file__
FIELDS = {"id": "id", "escalated": "ts", "owner": "owner",
          "deadline": "ack_deadline", "ack": "acked_at",
          "resolved": "resolved_at"}
NOW = datetime(2026, 7, 30, 21, 0, tzinfo=timezone.utc)


def write(records):
    handle = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
    for record in records:
        handle.write(json.dumps(record) + "\n")
    handle.close()
    return handle.name


def status_of(records, fields=None, max_age_hours=24.0):
    result = ec.audit(records, fields or FIELDS, max_age_hours, NOW)
    result["clauses"] = ec.conformance(result)
    result["skipped_lines"] = 0
    result["status"] = ec.verdict(result)
    return result


class TestParseTs(unittest.TestCase):
    def test_accepts_trailing_z(self):
        self.assertEqual(ec.parse_ts("2026-07-30T10:00:00Z").hour, 10)

    def test_naive_is_treated_as_utc(self):
        self.assertEqual(ec.parse_ts("2026-07-30T10:00:00").tzinfo, timezone.utc)

    def test_garbage_returns_none(self):
        for value in ("not-a-date", "", None, 17, True):
            self.assertIsNone(ec.parse_ts(value))


class TestPresent(unittest.TestCase):
    def test_empty_values_are_absent(self):
        for value in (None, "", "   ", False):
            self.assertFalse(ec.present({"f": value}, "f"))

    def test_missing_key_is_absent(self):
        self.assertFalse(ec.present({}, "f"))

    def test_zero_is_present(self):
        """0 is a legitimate id. Only None/False/blank count as absent."""
        self.assertTrue(ec.present({"f": 0}, "f"))


class TestAudit(unittest.TestCase):
    def test_fully_conforming_queue_passes_every_clause(self):
        records = [{"id": "c-1", "ts": "2026-07-30T10:00:00Z",
                    "owner": "ops@example.com",
                    "ack_deadline": "2026-07-31T10:00:00Z",
                    "acked_at": "2026-07-30T11:00:00Z",
                    "resolved_at": "2026-07-30T12:00:00Z"}]
        result = status_of(records)
        self.assertEqual(result["recorded_ack_rate"], 1.0)
        self.assertEqual(result["status"], "conformant")
        self.assertTrue(all(result["clauses"].values()))

    def test_unacknowledged_item_past_max_age_breaches(self):
        records = [{"ts": "2026-07-01T10:00:00Z", "owner": "ops",
                    "ack_deadline": "2026-07-02T10:00:00Z"}]
        result = status_of(records)
        self.assertEqual(result["breaching_max_age"], 1)
        self.assertFalse(result["clauses"]["C4_age_is_an_event"])
        self.assertGreater(result["oldest_unacked_hours"], 600)

    def test_acknowledged_items_are_not_aged(self):
        """An acked item is out of the queue's hands; its age is not a breach."""
        records = [{"ts": "2026-01-01T00:00:00Z",
                    "acked_at": "2026-01-01T01:00:00Z"}]
        result = status_of(records)
        self.assertEqual(result["breaching_max_age"], 0)
        self.assertIsNone(result["oldest_unacked_hours"])

    def test_unparseable_timestamp_is_counted_not_dropped(self):
        result = status_of([{"ts": "nope"}])
        self.assertEqual(result["unparseable_timestamps"], 1)
        self.assertEqual(result["unageable"], 1)
        self.assertFalse(result["clauses"]["C4_age_is_an_event"])

    def test_empty_queue_yields_no_clauses(self):
        result = status_of([])
        self.assertEqual(result["total_escalated"], 0)
        self.assertIsNone(result["recorded_ack_rate"])
        self.assertEqual(result["clauses"], {})
        self.assertEqual(result["status"], "inconclusive")
        self.assertEqual(ec.exit_code(result["status"]), 2)

    def test_partial_acknowledgement_rate(self):
        records = [{"ts": "2026-07-30T10:00:00Z",
                    "acked_at": "2026-07-30T11:00:00Z"},
                   {"ts": "2026-07-30T10:00:00Z"}]
        result = status_of(records)
        self.assertEqual(result["recorded_ack_rate"], 0.5)
        self.assertFalse(result["clauses"]["C3_acknowledgement_recorded"])

    def test_custom_field_names(self):
        fields = dict(FIELDS, ack="handled_at", owner="assignee")
        records = [{"ts": "2026-07-30T10:00:00Z", "assignee": "sam",
                    "ack_deadline": "2026-07-31T10:00:00Z",
                    "handled_at": "2026-07-30T10:30:00Z"}]
        result = status_of(records, fields)
        self.assertEqual(result["with_owner"], 1)
        self.assertEqual(result["with_recorded_ack"], 1)

    def test_non_timestamp_ack_is_not_acknowledgement(self):
        """The v0.1 false success: 'automated' used to satisfy C3."""
        records = [{"id": "t-1", "ts": "2026-07-30T10:00:00Z",
                    "owner": "alice", "ack_deadline": "2026-07-31T10:00:00Z",
                    "acked_at": "automated"}]
        result = status_of(records)
        self.assertEqual(result["with_recorded_ack"], 0)
        self.assertEqual(result["invalid_ack_values"], 1)
        self.assertFalse(result["clauses"]["C3_acknowledgement_recorded"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["findings"][0]["code"], "invalid_ack")

    def test_non_timestamp_deadline_does_not_satisfy_c2(self):
        records = [{"id": "t-2", "ts": "2026-07-30T10:00:00Z",
                    "owner": "alice", "ack_deadline": "eventually",
                    "acked_at": "2026-07-30T10:30:00Z"}]
        result = status_of(records)
        self.assertEqual(result["with_deadline"], 0)
        self.assertEqual(result["invalid_deadlines"], 1)
        self.assertFalse(result["clauses"]["C2_deadline_set"])

    def test_late_acknowledgement_breaks_chronology(self):
        records = [{"id": "t-3", "ts": "2026-07-30T10:00:00Z",
                    "owner": "alice",
                    "ack_deadline": "2026-07-30T12:00:00Z",
                    "acked_at": "2026-07-30T14:00:00Z"}]
        result = status_of(records)
        self.assertEqual(result["late_acknowledgements"], 1)
        self.assertFalse(result["clauses"]["C5_chronology_valid"])
        self.assertEqual(result["status"], "failed")

    def test_ack_before_escalation_breaks_chronology(self):
        records = [{"id": "t-4", "ts": "2026-07-30T10:00:00Z",
                    "owner": "alice",
                    "ack_deadline": "2026-07-30T12:00:00Z",
                    "acked_at": "2026-07-30T09:00:00Z"}]
        result = status_of(records)
        self.assertEqual(result["ack_before_escalation"], 1)
        self.assertFalse(result["clauses"]["C5_chronology_valid"])

    def test_future_escalation_is_unageable(self):
        records = [{"id": "t-5", "ts": "2030-01-01T00:00:00Z",
                    "owner": "alice",
                    "ack_deadline": "2030-01-02T00:00:00Z"}]
        result = status_of(records)
        self.assertEqual(result["future_escalations"], 1)
        self.assertEqual(result["unageable"], 1)
        self.assertFalse(result["clauses"]["C4_age_is_an_event"])

    def test_ack_with_unreadable_deadline_is_unverifiable(self):
        records = [{"id": "t-6", "ts": "2026-07-30T10:00:00Z",
                    "owner": "alice", "ack_deadline": "eventually",
                    "acked_at": "2026-07-30T10:30:00Z"}]
        result = status_of(records)
        self.assertEqual(result["unverifiable_chronology"], 1)
        self.assertFalse(result["clauses"]["C5_chronology_valid"])

    def test_invalid_resolution_is_counted_not_fatal(self):
        """Resolution is reported, not one of the five conformance clauses."""
        records = [{"id": "t-7", "ts": "2026-07-30T10:00:00Z",
                    "owner": "alice",
                    "ack_deadline": "2026-07-30T12:00:00Z",
                    "acked_at": "2026-07-30T10:30:00Z",
                    "resolved_at": "done"}]
        result = status_of(records)
        self.assertEqual(result["resolved"], 0)
        self.assertEqual(result["invalid_resolutions"], 1)
        self.assertEqual(result["status"], "conformant")


class TestCli(unittest.TestCase):
    def run_cli(self, path, *args):
        proc = subprocess.run([sys.executable, SCRIPT, path, *args],
                              capture_output=True, text=True)
        return proc

    def test_conforming_queue_exits_zero(self):
        path = write([{"ts": "2026-07-30T10:00:00Z", "owner": "ops",
                       "ack_deadline": "2026-07-31T10:00:00Z",
                       "acked_at": "2026-07-30T11:00:00Z",
                       "resolved_at": "2026-07-30T12:00:00Z"}])
        proc = self.run_cli(path)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("recorded acknowledgement rate: 100%", proc.stdout)
        self.assertIn("CONFORMANT", proc.stdout)
        os.unlink(path)

    def test_failing_queue_exits_one(self):
        path = write([{"ts": "2026-07-30T10:00:00Z"}])
        proc = self.run_cli(path)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("FAIL  C3_acknowledgement_recorded", proc.stdout)
        self.assertIn("FAILED", proc.stdout)
        os.unlink(path)

    def test_empty_queue_is_inconclusive_not_pass(self):
        path = write([])
        proc = self.run_cli(path)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("INCONCLUSIVE", proc.stdout)
        os.unlink(path)

    def test_empty_queue_json_is_inconclusive_not_pass(self):
        """The v0.1 false success: empty --json exited 0 with no clauses."""
        path = write([])
        proc = self.run_cli(path, "--json")
        payload = json.loads(proc.stdout)
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(payload["status"], "inconclusive")
        self.assertEqual(payload["clauses"], {})
        self.assertEqual(payload["total_escalated"], 0)
        os.unlink(path)

    def test_malformed_line_warns_and_continues(self):
        path = write([{"ts": "2026-07-30T10:00:00Z"}])
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("{not json\n")
        proc = self.run_cli(path)
        self.assertIn("not valid JSON, skipped", proc.stderr)
        self.assertIn("escalated items          1", proc.stdout)
        os.unlink(path)

    def test_skipped_line_blocks_conformant_verdict(self):
        path = write([{"ts": "2026-07-30T10:00:00Z", "owner": "ops",
                       "ack_deadline": "2026-07-31T10:00:00Z",
                       "acked_at": "2026-07-30T11:00:00Z"}])
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("[1, 2, 3]\n")
        proc = self.run_cli(path, "--json")
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["skipped_lines"], 1)
        self.assertEqual(payload["status"], "inconclusive")
        self.assertEqual(proc.returncode, 2)
        os.unlink(path)

    def test_json_mode_is_machine_readable(self):
        path = write([{"ts": "2026-07-30T10:00:00Z", "owner": "ops"}])
        proc = self.run_cli(path, "--json")
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["spec_version"], ec.SPEC_VERSION)
        self.assertEqual(payload["with_owner"], 1)
        self.assertFalse(payload["clauses"]["C3_acknowledgement_recorded"])
        self.assertNotIn("human_arrival_rate", payload)
        self.assertNotIn("acknowledged_by_human", payload)
        self.assertIn("checked_at", payload)
        os.unlink(path)

    def test_json_reports_invalid_ack_as_finding(self):
        path = write([{"id": "t-1", "ts": "2026-07-30T10:00:00Z",
                       "owner": "alice",
                       "ack_deadline": "eventually",
                       "acked_at": "automated"}])
        proc = self.run_cli(path, "--json")
        payload = json.loads(proc.stdout)
        codes = {item["code"] for item in payload["findings"]}
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(payload["status"], "failed")
        self.assertIn("invalid_ack", codes)
        self.assertIn("invalid_deadline", codes)
        os.unlink(path)

    def test_now_makes_age_deterministic(self):
        path = write([{"ts": "2026-07-30T10:00:00Z", "owner": "ops",
                       "ack_deadline": "2026-07-31T10:00:00Z",
                       "acked_at": "2026-07-30T11:00:00Z"}])
        proc = self.run_cli(path, "--json",
                            "--now", "2026-07-30T21:00:00Z")
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "conformant")
        self.assertEqual(payload["checked_at"], "2026-07-30T21:00:00+00:00")
        os.unlink(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
