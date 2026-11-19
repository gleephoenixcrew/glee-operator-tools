"""Regression tests for consuming ACK evidence after it has been written."""

import hashlib
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
    verify_message,
    verify_task,
)


TASK = "task-revalidation"
RECIPIENT = "agent-07"
ORIGINAL = b"the exact bytes\n"


def _transfer(root: Path) -> dict:
    create_task(root, TASK, "glee-control", RECIPIENT, "Inspect artifact", ["byte-identical"])
    source = root / "artifact.txt"
    source.write_bytes(ORIGINAL)
    manifest = send_file(root, TASK, "glee-control", RECIPIENT, source)
    return json.loads(manifest.read_text(encoding="utf-8"))


def _ack(root: Path, manifest: dict) -> Path:
    return acknowledge(root, TASK, manifest["message_id"], RECIPIENT)


def _assert_rejected_ack(root: Path, manifest: dict, ack_path: Path) -> None:
    """Every public consumer must reject the ACK and retain its original evidence."""
    before = ack_path.read_bytes()
    message_id = manifest["message_id"]
    assert message_id in [m["message_id"] for m in inbox(root, RECIPIENT)]
    assert verify_message(root, TASK, message_id), "verification accepted invalid ACK evidence"
    assert main(["--root", str(root), "verify", "--task", TASK, "--message", message_id]) == 3
    with pytest.raises(TransferIntegrityError):
        _ack(root, manifest)
    assert ack_path.read_bytes() == before, "rejected ACK evidence was silently overwritten"


def test_same_length_corruption_after_ack_is_pending_and_restoration_is_recognized(tmp_path: Path):
    manifest = _transfer(tmp_path)
    ack_path = _ack(tmp_path, manifest)
    before = ack_path.read_bytes()
    payload = tmp_path / manifest["files"][0]["path"]
    assert inbox(tmp_path, RECIPIENT) == []

    corrupt = b"THE EXACT BYTES\n"
    assert len(corrupt) == len(ORIGINAL)
    payload.write_bytes(corrupt)
    _assert_rejected_ack(tmp_path, manifest, ack_path)

    payload.write_bytes(ORIGINAL)
    assert inbox(tmp_path, RECIPIENT) == []
    assert verify_message(tmp_path, TASK, manifest["message_id"]) == []
    assert _ack(tmp_path, manifest) == ack_path
    assert ack_path.read_bytes() == before


@pytest.mark.parametrize("field,wrong", [
    ("schema", "glee.exchange.receipt.v1"),
    ("task_id", "other-task"),
    ("message_id", "other-message"),
    ("agent", "other-agent"),
])
@pytest.mark.parametrize("omit", [False, True], ids=["wrong", "missing"])
def test_ack_must_bind_identity(tmp_path: Path, field: str, wrong: str, omit: bool):
    manifest = _transfer(tmp_path)
    ack_path = _ack(tmp_path, manifest)
    ack = json.loads(ack_path.read_text(encoding="utf-8"))
    if omit:
        del ack[field]
    else:
        ack[field] = wrong
    ack_path.write_text(json.dumps(ack), encoding="utf-8")
    _assert_rejected_ack(tmp_path, manifest, ack_path)


@pytest.mark.parametrize("timestamp", [None, "", {"claimed": "2026-11-13T00:00:00Z"}])
def test_ack_requires_timestamp_evidence(tmp_path: Path, timestamp):
    manifest = _transfer(tmp_path)
    ack_path = _ack(tmp_path, manifest)
    ack = json.loads(ack_path.read_text(encoding="utf-8"))
    if timestamp is None:
        del ack["acked_at"]
    else:
        ack["acked_at"] = timestamp
    ack_path.write_text(json.dumps(ack), encoding="utf-8")
    _assert_rejected_ack(tmp_path, manifest, ack_path)


@pytest.mark.parametrize("content", ["{", "[]", "null", '"ack"', "true", "42"])
def test_malformed_ack_stays_pending_without_breaking_other_messages(tmp_path: Path, content: str):
    manifest = _transfer(tmp_path)
    ack_path = _ack(tmp_path, manifest)
    ack_path.write_text(content, encoding="utf-8")
    second_path = send_file(tmp_path, TASK, "glee-control", RECIPIENT, tmp_path / "artifact.txt")
    second = json.loads(second_path.read_text(encoding="utf-8"))

    _assert_rejected_ack(tmp_path, manifest, ack_path)
    assert {m["message_id"] for m in inbox(tmp_path, RECIPIENT)} == {
        manifest["message_id"], second["message_id"],
    }


@pytest.mark.parametrize("field", ["verified", "files", "manifest_sha256"])
def test_missing_verification_evidence_is_not_reused(tmp_path: Path, field: str):
    manifest = _transfer(tmp_path)
    ack_path = _ack(tmp_path, manifest)
    ack = json.loads(ack_path.read_text(encoding="utf-8"))
    del ack[field]
    ack_path.write_text(json.dumps(ack), encoding="utf-8")
    _assert_rejected_ack(tmp_path, manifest, ack_path)


def test_valid_ack_is_idempotent_and_does_not_hide_other_transfers(tmp_path: Path):
    manifest = _transfer(tmp_path)
    ack_path = _ack(tmp_path, manifest)
    before = ack_path.read_bytes()
    second_path = send_file(tmp_path, TASK, "glee-control", RECIPIENT, tmp_path / "artifact.txt")
    second = json.loads(second_path.read_text(encoding="utf-8"))

    assert _ack(tmp_path, manifest) == ack_path
    assert ack_path.read_bytes() == before
    assert verify_message(tmp_path, TASK, manifest["message_id"]) == []
    assert [m["message_id"] for m in inbox(tmp_path, RECIPIENT)] == [second["message_id"]]


@pytest.mark.parametrize("field,wrong", [
    ("schema", "glee.exchange.receipt.v1"),
    ("task_id", "other-task"),
    ("message_id", "other-message"),
])
def test_manifest_identity_must_match_transfer_before_ack(tmp_path: Path, field: str, wrong: str):
    manifest = _transfer(tmp_path)
    message_id = manifest["message_id"]
    manifest_path = tmp_path / "exchange/tasks" / TASK / "transfers" / message_id / "manifest.json"
    manifest[field] = wrong
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(TransferIntegrityError):
        acknowledge(tmp_path, TASK, message_id, RECIPIENT)
    assert not (tmp_path / "exchange/tasks" / TASK / "acks" / f"{message_id}.json").exists()
    assert inbox(tmp_path, RECIPIENT) == [manifest]
    assert verify_message(tmp_path, TASK, message_id)
    assert set(verify_task(tmp_path, TASK)) == {message_id}


@pytest.mark.parametrize("field,wrong", [
    ("task_id", "other-task"),
    ("message_id", "other-message"),
])
def test_agreeing_ack_and_manifest_still_must_match_actual_transfer_path(
    tmp_path: Path, field: str, wrong: str,
):
    manifest = _transfer(tmp_path)
    message_id = manifest["message_id"]
    ack_path = _ack(tmp_path, manifest)
    ack = json.loads(ack_path.read_text(encoding="utf-8"))
    manifest_path = tmp_path / "exchange/tasks" / TASK / "transfers" / message_id / "manifest.json"
    manifest[field] = wrong
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    ack[field] = wrong
    ack["manifest_sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    ack_path.write_text(json.dumps(ack), encoding="utf-8")
    before = ack_path.read_bytes()

    assert inbox(tmp_path, RECIPIENT) == [manifest]
    assert verify_message(tmp_path, TASK, message_id)
    assert set(verify_task(tmp_path, TASK)) == {message_id}
    assert main(["--root", str(tmp_path), "verify", "--task", TASK]) == 3
    with pytest.raises(TransferIntegrityError):
        acknowledge(tmp_path, TASK, message_id, RECIPIENT)
    assert ack_path.read_bytes() == before


def test_legacy_ack_can_be_explicitly_archived_and_reverified(tmp_path: Path):
    manifest = _transfer(tmp_path)
    ack_path = _ack(tmp_path, manifest)
    legacy = json.loads(ack_path.read_text(encoding="utf-8"))
    del legacy["verified"]
    del legacy["files"]
    ack_path.write_text(json.dumps(legacy), encoding="utf-8")
    legacy_bytes = ack_path.read_bytes()
    _assert_rejected_ack(tmp_path, manifest, ack_path)

    archive_path = ack_path.with_suffix(".legacy.json")
    ack_path.rename(archive_path)
    assert archive_path.read_bytes() == legacy_bytes
    assert verify_message(tmp_path, TASK, manifest["message_id"]) == []
    assert _ack(tmp_path, manifest) == ack_path
    assert inbox(tmp_path, RECIPIENT) == []
    assert archive_path.read_bytes() == legacy_bytes
    assert json.loads(ack_path.read_text(encoding="utf-8"))["verified"] is True
