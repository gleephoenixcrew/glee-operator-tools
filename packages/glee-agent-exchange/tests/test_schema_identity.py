"""The JSON schema must constrain every record's identity fields the way the CLI does."""

import json
from pathlib import Path

import pytest

from glee_agent_exchange.cli import (
    ID_RE,
    acknowledge,
    create_task,
    send_file,
    write_receipt,
)

SCHEMA = json.loads(
    (Path(__file__).resolve().parents[1] / "schemas" / "exchange.schema.json").read_text(encoding="utf-8")
)
IDENTITY_FIELDS = {"receipt_id", "message_id", "task_id", "agent", "from", "to"}
EXPECTED_IDENTITY = {
    "task": {"task_id", "from", "to"},
    "message": {"message_id", "task_id", "from", "to"},
    "ack": {"task_id", "message_id", "agent"},
    "receipt": {"receipt_id", "task_id", "agent"},
}
ID_PROBES = [".", "..", "...", "a", ".hidden", "version..2", "_worker", "a/b", "a\n", "..\n", "...\n",
             "a\nb", "\n", "a\r", "", " a", "é", "rcpt-20261119T120000Z-deadbeef"]


@pytest.mark.parametrize("record", sorted(EXPECTED_IDENTITY))
def test_every_identity_field_uses_the_shared_id_definition(record):
    definition = SCHEMA["$defs"][record]
    declared = IDENTITY_FIELDS & (set(definition["required"]) | set(definition["properties"]))
    assert declared == EXPECTED_IDENTITY[record]
    for field in sorted(EXPECTED_IDENTITY[record]):
        assert field in definition["required"], f"{record}.{field} not required"
        assert definition["properties"].get(field) == {"$ref": "#/$defs/id"}, f"{record}.{field}"


def _schema_id_ok_python_semantics(value: str) -> bool:
    # JSON Schema "pattern" is unanchored search; Python validators use re.search,
    # where "$" also matches before a trailing newline.
    import re

    definition = SCHEMA["$defs"]["id"]
    if not re.search(definition["pattern"], value):
        return False
    banned = definition.get("not", {}).get("pattern")
    return not (banned and re.search(banned, value))


@pytest.mark.parametrize("value", ID_PROBES)
def test_schema_id_agrees_with_cli_under_search_semantics(value):
    assert _schema_id_ok_python_semantics(value) == bool(ID_RE.fullmatch(value))


def test_schema_id_agrees_with_cli_under_a_real_validator():
    jsonschema = pytest.importorskip("jsonschema")
    validator = jsonschema.Draft202012Validator({"$defs": SCHEMA["$defs"], "$ref": "#/$defs/id"})
    disagreements = [v for v in ID_PROBES if validator.is_valid(v) != bool(ID_RE.fullmatch(v))]
    assert not disagreements


def _records(root: Path) -> dict[str, dict]:
    create_task(root, "t-1", "glee-control", "agent-07", "Inspect bytes", ["verify"])
    artifact = root / "artifact.txt"
    artifact.write_bytes(b"exact payload\n")
    manifest = send_file(root, "t-1", "glee-control", "agent-07", artifact)
    paths = {
        "task": root / "exchange/tasks/t-1/task.json",
        "message": manifest,
        "ack": acknowledge(root, "t-1", manifest.parent.name, "agent-07"),
        "receipt": write_receipt(root, "t-1", "agent-07", "accepted", "done", ["pytest: passed"]),
    }
    return {name: json.loads(path.read_text(encoding="utf-8")) for name, path in paths.items()}


def test_schema_accepts_generated_records_and_rejects_unsafe_evidence(tmp_path: Path):
    jsonschema = pytest.importorskip("jsonschema")
    validator = jsonschema.Draft202012Validator(SCHEMA)
    records = _records(tmp_path)
    for name, record in records.items():
        assert not list(validator.iter_errors(record)), name
        for field in sorted(IDENTITY_FIELDS & set(record)):
            for unsafe in (".", ".."):
                assert list(validator.iter_errors({**record, field: unsafe})), f"{name}.{field}={unsafe!r}"
    for files in ([42], [{}], [{"path": "x", "bytes": -1, "sha256": "0" * 64}]):
        assert list(validator.iter_errors({**records["message"], "files": files})), files
    assert list(validator.iter_errors({**records["receipt"], "evidence": "not a list"}))
