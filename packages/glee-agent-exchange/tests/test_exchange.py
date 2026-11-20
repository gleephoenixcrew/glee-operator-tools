from pathlib import Path

from glee_agent_exchange.cli import acknowledge, create_task, inbox, send_file, write_receipt


def test_file_round_trip(tmp_path: Path):
    create_task(tmp_path, "task-001", "glee-control", "agent-07", "Inspect artifact", ["return verified receipt"])
    source = tmp_path / "report.txt"
    source.write_text("evidence\n", encoding="utf-8")
    manifest_path = send_file(tmp_path, "task-001", "glee-control", "agent-07", source, "inspect this")
    manifest = __import__("json").loads(manifest_path.read_text())
    assert len(manifest["files"][0]["sha256"]) == 64
    assert len(inbox(tmp_path, "agent-07")) == 1
    acknowledge(tmp_path, "task-001", manifest["message_id"], "agent-07")
    assert inbox(tmp_path, "agent-07") == []


def test_wrong_recipient_cannot_ack(tmp_path: Path):
    create_task(tmp_path, "task-002", "glee-control", "agent-01", "Inspect", [])
    source = tmp_path / "x.txt"
    source.write_text("x", encoding="utf-8")
    manifest_path = send_file(tmp_path, "task-002", "glee-control", "agent-01", source)
    manifest = __import__("json").loads(manifest_path.read_text())
    try:
        acknowledge(tmp_path, "task-002", manifest["message_id"], "agent-02")
    except PermissionError:
        pass
    else:
        raise AssertionError("wrong recipient ack was accepted")


def test_receipt(tmp_path: Path):
    create_task(tmp_path, "task-003", "glee-control", "agent-03", "Build", ["tests pass"])
    path = write_receipt(tmp_path, "task-003", "agent-03", "review", "implemented", ["pytest: 3 passed"])
    text = path.read_text()
    assert '"status": "review"' in text
    assert "pytest: 3 passed" in text
