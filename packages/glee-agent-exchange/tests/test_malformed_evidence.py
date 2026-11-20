"""Regression cases for malformed transfer evidence and unsafe ID segments."""

import hashlib
import json
import re
from pathlib import Path

import pytest

from glee_agent_exchange.cli import (
    TransferIntegrityError,
    _check_id,
    acknowledge,
    create_task,
    inbox,
    main,
    send_file,
    task_dir,
    verify_message,
)


TASK = "task-malformed"
RECIPIENT = "agent-07"


def _transfer(root: Path) -> tuple[dict, Path]:
    create_task(root, TASK, "glee-control", RECIPIENT, "Inspect bytes", ["verify"])
    artifact = root / "artifact.txt"
    artifact.write_bytes(b"exact payload\n")
    path = send_file(root, TASK, "glee-control", RECIPIENT, artifact)
    return json.loads(path.read_text(encoding="utf-8")), path


@pytest.mark.parametrize("files", [None, 42, [], "not a list"], ids=["null", "number", "empty", "string"])
def test_invalid_manifest_files_cannot_crash_ack_consumers(tmp_path: Path, files):
    manifest, manifest_path = _transfer(tmp_path)
    message_id = manifest["message_id"]
    ack_path = acknowledge(tmp_path, TASK, message_id, RECIPIENT)

    # Simulate correlated tampering: the ACK digest is updated to match an invalid manifest.
    manifest["files"] = files
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    ack = json.loads(ack_path.read_text(encoding="utf-8"))
    ack["manifest_sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    ack_path.write_text(json.dumps(ack), encoding="utf-8")
    original_ack = ack_path.read_bytes()

    assert inbox(tmp_path, RECIPIENT) == [manifest]
    problems = verify_message(tmp_path, TASK, message_id)
    assert any("manifest lists no files" in problem for problem in problems)
    assert any("ack does not prove" in problem for problem in problems)
    assert main(["--root", str(tmp_path), "verify", "--task", TASK, "--message", message_id]) == 3
    with pytest.raises(TransferIntegrityError, match="manifest lists no files"):
        acknowledge(tmp_path, TASK, message_id, RECIPIENT)
    assert ack_path.read_bytes() == original_ack


@pytest.mark.parametrize("unsafe", [".", ".."])
def test_dot_segments_rejected_by_all_id_paths(tmp_path: Path, unsafe: str):
    with pytest.raises(ValueError, match="task_id"):
        task_dir(tmp_path, unsafe)
    for label in ("sender", "recipient", "agent", "message_id"):
        with pytest.raises(ValueError, match=label):
            _check_id(unsafe, label)
    assert not (tmp_path / "exchange").exists()


def test_schema_id_pattern_rejects_dot_segments_and_preserves_regular_ids():
    schema_path = Path(__file__).resolve().parents[1] / "schemas" / "exchange.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    pattern = schema["$defs"]["id"]["pattern"]
    for unsafe in (".", ".."):
        assert re.fullmatch(pattern, unsafe) is None
    for safe in ("task-123", "agent.07", ".hidden", "version..2", "_worker"):
        assert re.fullmatch(pattern, safe) is not None


@pytest.mark.parametrize("bad_bytes", [b'{"files": [', b"\xff"])
def test_corrupt_manifest_is_integrity_error_not_usage_error(tmp_path: Path, bad_bytes: bytes, capsys):
    manifest, manifest_path = _transfer(tmp_path)
    manifest_path.write_bytes(bad_bytes)
    commands = [
        ["verify", "--task", TASK, "--message", manifest["message_id"]],
        ["ack", "--task", TASK, "--message", manifest["message_id"], "--agent", RECIPIENT],
        ["inbox", "--to", RECIPIENT],
    ]
    for command in commands:
        assert main(["--root", str(tmp_path), *command]) == 3
        output = capsys.readouterr()
        assert "manifest.json" in output.err
        assert not output.out
    assert not (tmp_path / "exchange/tasks" / TASK / "acks" / f"{manifest['message_id']}.json").exists()


@pytest.mark.parametrize("missing_field", ["message_id", "task_id", "from"])
def test_text_inbox_prints_pending_malformed_manifest(tmp_path: Path, missing_field: str, capsys):
    manifest, manifest_path = _transfer(tmp_path)
    del manifest[missing_field]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert main(["--root", str(tmp_path), "inbox", "--to", RECIPIENT]) == 0
    text_output = capsys.readouterr()
    assert "<missing>" in text_output.out
    assert not text_output.err

    assert main(["--root", str(tmp_path), "inbox", "--to", RECIPIENT, "--json"]) == 0
    json_output = capsys.readouterr()
    assert json.loads(json_output.out) == [manifest]
