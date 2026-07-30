#!/usr/bin/env python3
"""Tests for escalation_conformance. Stdlib only: python3 test_escalation_conformance.py"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

import escalation_conformance as ec

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "escalation_conformance.py")
FIELDS = {"escalated": "ts", "owner": "owner", "deadline": "ack_deadline",
          "ack": "acked_at", "resolved": "resolved_at"}
NOW = datetime(2026, 7, 30, 21, 0, tzinfo=timezone.utc)


def write(records):
    handle = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
    for record in records:
        handle.write(json.dumps(record) + "\n")
    handle.close()
    return handle.name


class TestParseTs(unittest.TestCase):
    def test_accepts_trailing_z(self):
        self.assertEqual(ec.parse_ts("2026-07-30T10:00:00Z").hour, 10)

    def test_naive_is_treated_as_utc(self):
        self.assertEqual(ec.parse_ts("2026-07-30T10:00:00").tzinfo, timezone.utc)

    def test_garbage_returns_none(self):
        for value in ("not-a-date", "", None, 17):
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
        records = [{"ts": "2026-07-30T10:00:00Z", "owner": "ops@example.com",
                    "ack_deadline": "2026-07-31T10:00:00Z",
                    "acked_at": "2026-07-30T11:00:00Z",
                    "resolved_at": "2026-07-30T12:00:00Z"}]
        result = ec.audit(records, FIELDS, 24.0, NOW)
        self.assertEqual(result["human_arrival_rate"], 1.0)
        self.assertTrue(all(ec.conformance(result).values()))

    def test_unacknowledged_item_past_max_age_breaches(self):
        records = [{"ts": "2026-07-01T10:00:00Z", "owner": "ops", "ack_deadline": "x"}]
        result = ec.audit(records, FIELDS, 24.0, NOW)
        self.assertEqual(result["breaching_max_age"], 1)
        self.assertFalse(ec.conformance(result)["C4_age_is_an_event"])
        self.assertGreater(result["oldest_unacked_hours"], 600)

    def test_acknowledged_items_are_not_aged(self):
        """An acked item is out of the queue's hands; its age is not a breach."""
        records = [{"ts": "2026-01-01T00:00:00Z", "acked_at": "2026-01-01T01:00:00Z"}]
        result = ec.audit(records, FIELDS, 24.0, NOW)
        self.assertEqual(result["breaching_max_age"], 0)
        self.assertIsNone(result["oldest_unacked_hours"])

    def test_unparseable_timestamp_is_counted_not_dropped(self):
        result = ec.audit([{"ts": "nope"}], FIELDS, 24.0, NOW)
        self.assertEqual(result["unparseable_timestamps"], 1)

    def test_empty_queue_yields_no_clauses(self):
        result = ec.audit([], FIELDS, 24.0, NOW)
        self.assertEqual(result["total_escalated"], 0)
        self.assertIsNone(result["human_arrival_rate"])
        self.assertEqual(ec.conformance(result), {})

    def test_partial_acknowledgement_rate(self):
        records = [{"ts": "2026-07-30T10:00:00Z", "acked_at": "2026-07-30T11:00:00Z"},
                   {"ts": "2026-07-30T10:00:00Z"}]
        result = ec.audit(records, FIELDS, 24.0, NOW)
        self.assertEqual(result["human_arrival_rate"], 0.5)
        self.assertFalse(ec.conformance(result)["C3_human_acknowledged"])

    def test_custom_field_names(self):
        fields = dict(FIELDS, ack="handled_at", owner="assignee")
        records = [{"ts": "2026-07-30T10:00:00Z", "assignee": "sam",
                    "handled_at": "2026-07-30T10:30:00Z"}]
        result = ec.audit(records, fields, 24.0, NOW)
        self.assertEqual(result["with_owner"], 1)
        self.assertEqual(result["acknowledged_by_human"], 1)


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
        self.assertIn("human arrival rate: 100%", proc.stdout)
        os.unlink(path)

    def test_failing_queue_exits_one(self):
        path = write([{"ts": "2026-07-30T10:00:00Z"}])
        proc = self.run_cli(path)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("FAIL  C3_human_acknowledged", proc.stdout)
        os.unlink(path)

    def test_empty_queue_is_inconclusive_not_pass(self):
        path = write([])
        proc = self.run_cli(path)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("INCONCLUSIVE", proc.stdout)
        os.unlink(path)

    def test_malformed_line_warns_and_continues(self):
        path = write([{"ts": "2026-07-30T10:00:00Z"}])
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("{not json\n")
        proc = self.run_cli(path)
        self.assertIn("not valid JSON, skipped", proc.stderr)
        self.assertIn("escalated items          1", proc.stdout)
        os.unlink(path)

    def test_json_mode_is_machine_readable(self):
        path = write([{"ts": "2026-07-30T10:00:00Z", "owner": "ops"}])
        proc = self.run_cli(path, "--json")
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["spec_version"], ec.SPEC_VERSION)
        self.assertEqual(payload["with_owner"], 1)
        self.assertFalse(payload["clauses"]["C3_human_acknowledged"])
        os.unlink(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
