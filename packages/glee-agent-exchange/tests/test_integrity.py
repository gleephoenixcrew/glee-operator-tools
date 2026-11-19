import json
from pathlib import Path

import pytest

from glee_agent_exchange.cli import (
    TransferIntegrityError,
    acknowledge,
    create_task,
    inbox,
    main,
    send_file,
    verify_task,
)


def _transfer(root: Path, task_id: str = "task-010") -> tuple[dict, Path]:
    create_task(root, task_id, "glee-control", "agent-07", "Inspect artifact", ["byte-identical"])
    source = root / "artifact.txt"
    source.write_text("the exact bytes\n", encoding="utf-8")
    manifest_path = send_file(root, task_id, "glee-control", "agent-07", source, "verify me")
    return json.loads(manifest_path.read_text()), manifest_path


def test_ack_refuses_when_file_missing(tmp_path: Path):
    manifest, _ = _transfer(tmp_path)
    target = tmp_path / manifest["files"][0]["path"]
    target.unlink()

    with pytest.raises(TransferIntegrityError, match="missing from disk"):
        acknowledge(tmp_path, "task-010", manifest["message_id"], "agent-07")

    ack = tmp_path / "exchange/tasks/task-010/acks" / f"{manifest['message_id']}.json"
    assert not ack.exists(), "an ACK was written for a missing artifact"
    assert [m["message_id"] for m in inbox(tmp_path, "agent-07")] == [manifest["message_id"]]


def test_ack_refuses_when_bytes_corrupted(tmp_path: Path):
    manifest, _ = _transfer(tmp_path)
    target = tmp_path / manifest["files"][0]["path"]
    target.write_text("THE EXACT BYTES\n", encoding="utf-8")  # same length, different bytes

    with pytest.raises(TransferIntegrityError, match="sha256 mismatch"):
        acknowledge(tmp_path, "task-010", manifest["message_id"], "agent-07")

    ack = tmp_path / "exchange/tasks/task-010/acks" / f"{manifest['message_id']}.json"
    assert not ack.exists()
    assert len(inbox(tmp_path, "agent-07")) == 1


def test_ack_refuses_when_truncated(tmp_path: Path):
    manifest, _ = _transfer(tmp_path)
    target = tmp_path / manifest["files"][0]["path"]
    target.write_text("the exact", encoding="utf-8")

    with pytest.raises(TransferIntegrityError, match="byte length mismatch"):
        acknowledge(tmp_path, "task-010", manifest["message_id"], "agent-07")


def test_ack_records_verified_digests(tmp_path: Path):
    manifest, _ = _transfer(tmp_path)
    ack_path = acknowledge(tmp_path, "task-010", manifest["message_id"], "agent-07")
    ack = json.loads(ack_path.read_text())

    assert ack["verified"] is True
    assert ack["files"] == [{
        "path": manifest["files"][0]["path"],
        "bytes": manifest["files"][0]["bytes"],
        "sha256": manifest["files"][0]["sha256"],
    }]


def test_legacy_ack_without_verification_does_not_hide_transfer(tmp_path: Path):
    """An ACK written by the pre-verification code cannot prove delivery."""
    manifest, manifest_path = _transfer(tmp_path)
    ack = tmp_path / "exchange/tasks/task-010/acks" / f"{manifest['message_id']}.json"
    ack.parent.mkdir(parents=True)
    ack.write_text(json.dumps({
        "schema": "glee.exchange.ack.v1",
        "task_id": "task-010",
        "message_id": manifest["message_id"],
        "agent": "agent-07",
        "acked_at": "2026-09-25T00:00:00Z",
        "manifest_sha256": __import__("hashlib").sha256(manifest_path.read_bytes()).hexdigest(),
    }), encoding="utf-8")

    assert [m["message_id"] for m in inbox(tmp_path, "agent-07")] == [manifest["message_id"]]


def test_transfer_returns_to_pending_when_bytes_change_after_ack(tmp_path: Path):
    manifest, _ = _transfer(tmp_path)
    acknowledge(tmp_path, "task-010", manifest["message_id"], "agent-07")
    assert inbox(tmp_path, "agent-07") == []

    target = tmp_path / manifest["files"][0]["path"]
    target.write_text("rotated\n", encoding="utf-8")
    assert [m["message_id"] for m in inbox(tmp_path, "agent-07")] == [manifest["message_id"]]


def test_manifest_path_cannot_escape_root(tmp_path: Path):
    manifest, manifest_path = _transfer(tmp_path)
    manifest["files"][0]["path"] = "../outside.txt"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (tmp_path.parent / "outside.txt").write_text("the exact bytes\n", encoding="utf-8")

    with pytest.raises(TransferIntegrityError, match="escapes repository root"):
        acknowledge(tmp_path, "task-010", manifest["message_id"], "agent-07")


def test_verify_reports_clean_and_broken_state(tmp_path: Path):
    manifest, _ = _transfer(tmp_path)
    assert verify_task(tmp_path, "task-010") == {}

    target = tmp_path / manifest["files"][0]["path"]
    target.unlink()
    assert "missing from disk" in verify_task(tmp_path, "task-010")[manifest["message_id"]][0]


def test_cli_exit_codes(tmp_path: Path):
    manifest, _ = _transfer(tmp_path)
    (tmp_path / manifest["files"][0]["path"]).unlink()

    code = main(["--root", str(tmp_path), "ack", "--task", "task-010",
                 "--message", manifest["message_id"], "--agent", "agent-07"])
    assert code == 3, "integrity failure should be distinguishable from usage error (2)"

    code = main(["--root", str(tmp_path), "verify", "--task", "task-010"])
    assert code == 3
