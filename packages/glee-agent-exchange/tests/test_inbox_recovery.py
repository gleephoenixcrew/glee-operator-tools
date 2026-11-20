"""Damaged manifests must not hide or misidentify unrelated inbox work."""

import json
from pathlib import Path

import pytest

from glee_agent_exchange import cli


RECIPIENT = "agent-07"
OTHER_RECIPIENT = "agent-08"


def _transfer(root: Path, task: str, recipient: str = RECIPIENT) -> tuple[Path, dict]:
    cli.create_task(root, task, "glee-control", recipient, "Inspect bytes", ["verify"])
    source = root / f"{task}.txt"
    source.write_bytes(b"exact artifact bytes\n")
    path = cli.send_file(root, task, "glee-control", recipient, source, note="Review artifact")
    return path, json.loads(path.read_text(encoding="utf-8"))


def _evidence(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in (root / "exchange").rglob("*")
        if path.is_file()
    }


def _run(root: Path, json_mode: bool, capsys):
    args = ["--root", str(root), "inbox", "--to", RECIPIENT]
    if json_mode:
        args.append("--json")
    code = cli.main(args)
    return code, capsys.readouterr()


def _assert_rows(output: str, records: list[tuple[Path, dict]], json_mode: bool) -> None:
    if json_mode:
        assert json.loads(output) == [manifest for _, manifest in records]
    else:
        assert [line.split("\t")[:2] for line in output.splitlines()] == [
            [path.parent.name, path.parents[2].name] for path, _ in records
        ]


@pytest.mark.parametrize("json_mode", [False, True], ids=["text", "json"])
@pytest.mark.parametrize("bad_task", ["task-a", "task-z"], ids=["corrupt-first", "corrupt-last"])
@pytest.mark.parametrize(
    "bad_bytes", [b'{"to": "agent-08", ', b"\xff", b"[]"],
    ids=["truncated-json", "invalid-utf8", "nonobject-json"],
)
def test_corrupt_other_recipient_manifest_does_not_hide_pending_message(
    tmp_path: Path, json_mode: bool, bad_task: str, bad_bytes: bytes, capsys,
):
    good = _transfer(tmp_path, "task-m")
    bad_path, _ = _transfer(tmp_path, bad_task, OTHER_RECIPIENT)
    bad_path.write_bytes(bad_bytes)
    before = _evidence(tmp_path)

    code, output = _run(tmp_path, json_mode, capsys)

    assert code == 3
    _assert_rows(output.out, [good], json_mode)
    assert str(bad_path.relative_to(tmp_path)) in output.err
    assert "Traceback" not in output.err
    assert _evidence(tmp_path) == before


@pytest.mark.parametrize("json_mode", [False, True], ids=["text", "json"])
def test_reports_every_corrupt_manifest_and_keeps_scanning(tmp_path: Path, json_mode: bool, capsys):
    first, _ = _transfer(tmp_path, "task-a")
    good = _transfer(tmp_path, "task-m")
    last, _ = _transfer(tmp_path, "task-z", OTHER_RECIPIENT)
    first.write_bytes(b"{")
    last.write_bytes(b"null")
    before = _evidence(tmp_path)

    code, output = _run(tmp_path, json_mode, capsys)

    assert code == 3
    _assert_rows(output.out, [good], json_mode)
    for path in (first, last):
        assert str(path.relative_to(tmp_path)) in output.err
    assert _evidence(tmp_path) == before


@pytest.mark.parametrize("json_mode", [False, True], ids=["text", "json"])
def test_only_corrupt_manifest_is_an_incomplete_inbox_not_clean_empty(
    tmp_path: Path, json_mode: bool, capsys,
):
    path, _ = _transfer(tmp_path, "task-broken")
    path.write_bytes(b"{")
    before = _evidence(tmp_path)

    code, output = _run(tmp_path, json_mode, capsys)

    assert code == 3
    _assert_rows(output.out, [], json_mode)
    assert str(path.relative_to(tmp_path)) in output.err
    assert _evidence(tmp_path) == before


@pytest.mark.parametrize("json_mode", [False, True], ids=["text", "json"])
@pytest.mark.parametrize("state", ["empty", "pending", "acknowledged", "other-recipient"])
def test_clean_inbox_exit_codes_and_payloads_remain_compatible(
    tmp_path: Path, json_mode: bool, state: str, capsys,
):
    expected = []
    if state != "empty":
        path, manifest = _transfer(
            tmp_path, "task-clean", OTHER_RECIPIENT if state == "other-recipient" else RECIPIENT,
        )
        if state == "acknowledged":
            cli.acknowledge(tmp_path, "task-clean", path.parent.name, RECIPIENT)
        elif state == "pending":
            expected = [(path, manifest)]
    before = _evidence(tmp_path)

    code, output = _run(tmp_path, json_mode, capsys)

    assert code == (0 if expected else 1)
    _assert_rows(output.out, expected, json_mode)
    assert not output.err
    assert _evidence(tmp_path) == before


@pytest.mark.parametrize("error_type", [PermissionError, FileNotFoundError, IsADirectoryError])
def test_manifest_read_oserror_is_isolated_with_a_path_diagnostic(
    tmp_path: Path, error_type, monkeypatch, capsys,
):
    bad_path, _ = _transfer(tmp_path, "task-a", OTHER_RECIPIENT)
    good = _transfer(tmp_path, "task-m")
    before = _evidence(tmp_path)
    read = cli._json_read

    def failing_read(path: Path):
        if path == bad_path:
            raise error_type("manifest unavailable")
        return read(path)

    monkeypatch.setattr(cli, "_json_read", failing_read)
    code, output = _run(tmp_path, True, capsys)

    assert code == 3
    _assert_rows(output.out, [good], True)
    assert str(bad_path.relative_to(tmp_path)) in output.err
    assert "manifest unavailable" in output.err
    assert _evidence(tmp_path) == before


@pytest.mark.parametrize("field", ["message_id", "task_id"])
@pytest.mark.parametrize("omit", [False, True], ids=["forged", "missing"])
def test_text_uses_directory_identity_without_rewriting_manifest_or_weakening_ack(
    tmp_path: Path, field: str, omit: bool, capsys,
):
    path, manifest = _transfer(tmp_path, "task-actual")
    if omit:
        del manifest[field]
    else:
        manifest[field] = "claimed-elsewhere"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    before = _evidence(tmp_path)

    code, output = _run(tmp_path, False, capsys)

    assert code == 0
    _assert_rows(output.out, [(path, manifest)], False)
    assert "manifest identity mismatch" in output.out
    assert str(path.relative_to(tmp_path)) in output.out
    assert field in output.out
    assert ("<missing>" if omit else "claimed-elsewhere") in output.out

    code, output = _run(tmp_path, True, capsys)
    assert code == 0
    _assert_rows(output.out, [(path, manifest)], True)
    assert cli.inbox(tmp_path, RECIPIENT) == [manifest]
    with pytest.raises(cli.TransferIntegrityError):
        cli.acknowledge(tmp_path, "task-actual", path.parent.name, RECIPIENT)
    assert _evidence(tmp_path) == before


def test_manifest_cannot_spoof_location_and_json_preserves_extra_fields(tmp_path: Path, capsys):
    path, manifest = _transfer(tmp_path, "task-actual")
    manifest["task_id"] = "claimed-task"
    manifest["message_id"] = "claimed-message"
    manifest["location"] = {"task_id": "false-location", "message_id": "false-location"}
    manifest["manifest_path"] = "false-location/manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    before = _evidence(tmp_path)

    code, output = _run(tmp_path, False, capsys)
    assert code == 0
    _assert_rows(output.out, [(path, manifest)], False)
    assert str(path.relative_to(tmp_path)) in output.out

    code, output = _run(tmp_path, True, capsys)
    assert code == 0
    _assert_rows(output.out, [(path, manifest)], True)
    assert _evidence(tmp_path) == before


@pytest.mark.parametrize("json_mode", [False, True], ids=["text", "json"])
def test_partial_scan_preserves_valid_and_malformed_ack_semantics(
    tmp_path: Path, json_mode: bool, capsys,
):
    bad_path, _ = _transfer(tmp_path, "task-a")
    delivered_path, _ = _transfer(tmp_path, "task-b")
    cli.acknowledge(tmp_path, "task-b", delivered_path.parent.name, RECIPIENT)
    stale_path, stale_manifest = _transfer(tmp_path, "task-c")
    stale_ack = cli.acknowledge(tmp_path, "task-c", stale_path.parent.name, RECIPIENT)
    stale_ack.write_bytes(b"{")
    pending = _transfer(tmp_path, "task-d")
    bad_path.write_bytes(b"{")
    before = _evidence(tmp_path)

    code, output = _run(tmp_path, json_mode, capsys)

    assert code == 3
    _assert_rows(output.out, [(stale_path, stale_manifest), pending], json_mode)
    assert str(bad_path.relative_to(tmp_path)) in output.err
    assert _evidence(tmp_path) == before


def test_partial_scan_api_exposes_locations_and_errors_without_silencing_legacy_failure(tmp_path: Path):
    first, _ = _transfer(tmp_path, "task-a")
    good_path, good_manifest = _transfer(tmp_path, "task-m")
    last, _ = _transfer(tmp_path, "task-z", OTHER_RECIPIENT)
    first.write_bytes(b"{")
    last.write_bytes(b"null")
    before = _evidence(tmp_path)

    result = cli.scan_inbox(tmp_path, RECIPIENT)

    assert [(entry.manifest_path, entry.manifest) for entry in result.entries] == [(good_path, good_manifest)]
    assert len(result.errors) == 2
    for path in (first, last):
        assert any(str(path.relative_to(tmp_path)) in error for error in result.errors)
    with pytest.raises(cli.TransferIntegrityError):
        cli.inbox(tmp_path, RECIPIENT)
    assert _evidence(tmp_path) == before
