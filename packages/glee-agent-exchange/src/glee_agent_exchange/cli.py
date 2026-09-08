from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
RECEIPT_STATUSES = {"working", "blocked", "review", "accepted", "rejected"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _check_id(value: str, label: str) -> str:
    if not ID_RE.fullmatch(value):
        raise ValueError(f"{label} must match {ID_RE.pattern}: {value!r}")
    return value


def _json_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _json_read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def task_dir(root: Path, task_id: str) -> Path:
    return root / "exchange" / "tasks" / _check_id(task_id, "task_id")


def create_task(root: Path, task_id: str, sender: str, recipient: str, goal: str, acceptance: Iterable[str]) -> Path:
    sender = _check_id(sender, "sender")
    recipient = _check_id(recipient, "recipient")
    path = task_dir(root, task_id) / "task.json"
    if path.exists():
        raise FileExistsError(f"task already exists: {task_id}")
    _json_write(path, {
        "schema": "glee.exchange.task.v1",
        "task_id": task_id,
        "from": sender,
        "to": recipient,
        "goal": goal,
        "acceptance": list(acceptance),
        "created_at": _now(),
        "authority": "task packet defines scope; GitHub transport does not expand authority",
    })
    return path


def send_file(root: Path, task_id: str, sender: str, recipient: str, source: Path, note: str = "") -> Path:
    sender = _check_id(sender, "sender")
    recipient = _check_id(recipient, "recipient")
    source = source.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if not (task_dir(root, task_id) / "task.json").exists():
        raise FileNotFoundError(f"unknown task: {task_id}")
    message_id = f"msg-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    message_dir = task_dir(root, task_id) / "transfers" / message_id
    target = message_dir / "files" / source.name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    manifest = {
        "schema": "glee.exchange.message.v1",
        "message_id": message_id,
        "task_id": task_id,
        "from": sender,
        "to": recipient,
        "created_at": _now(),
        "note": note,
        "files": [{
            "path": str(target.relative_to(root)),
            "name": source.name,
            "bytes": target.stat().st_size,
            "sha256": _sha256(target),
        }],
    }
    manifest_path = message_dir / "manifest.json"
    _json_write(manifest_path, manifest)
    return manifest_path


def inbox(root: Path, recipient: str) -> list[dict]:
    recipient = _check_id(recipient, "recipient")
    pending: list[dict] = []
    tasks = root / "exchange" / "tasks"
    if not tasks.exists():
        return pending
    for manifest_path in sorted(tasks.glob("*/transfers/*/manifest.json")):
        manifest = _json_read(manifest_path)
        if manifest.get("to") != recipient:
            continue
        ack = manifest_path.parents[2] / "acks" / f"{manifest['message_id']}.json"
        if not ack.exists():
            pending.append(manifest)
    return pending


def acknowledge(root: Path, task_id: str, message_id: str, agent: str) -> Path:
    _check_id(message_id, "message_id")
    agent = _check_id(agent, "agent")
    manifest_path = task_dir(root, task_id) / "transfers" / message_id / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"unknown message: {message_id}")
    manifest = _json_read(manifest_path)
    if manifest.get("to") != agent:
        raise PermissionError(f"message is addressed to {manifest.get('to')}, not {agent}")
    path = task_dir(root, task_id) / "acks" / f"{message_id}.json"
    if path.exists():
        return path
    _json_write(path, {
        "schema": "glee.exchange.ack.v1",
        "task_id": task_id,
        "message_id": message_id,
        "agent": agent,
        "acked_at": _now(),
        "manifest_sha256": _sha256(manifest_path),
    })
    return path


def write_receipt(root: Path, task_id: str, agent: str, status: str, summary: str, evidence: Iterable[str]) -> Path:
    agent = _check_id(agent, "agent")
    if status not in RECEIPT_STATUSES:
        raise ValueError(f"status must be one of {sorted(RECEIPT_STATUSES)}")
    receipt_id = f"rcpt-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    path = task_dir(root, task_id) / "receipts" / f"{receipt_id}.json"
    _json_write(path, {
        "schema": "glee.exchange.receipt.v1",
        "receipt_id": receipt_id,
        "task_id": task_id,
        "agent": agent,
        "status": status,
        "summary": summary,
        "evidence": list(evidence),
        "created_at": _now(),
    })
    return path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="glee-exchange", description="Durable GitHub exchange protocol for GLEE agents")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root (default: cwd)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("task", help="create a task packet")
    p.add_argument("--id", required=True)
    p.add_argument("--from", dest="sender", required=True)
    p.add_argument("--to", dest="recipient", required=True)
    p.add_argument("--goal", required=True)
    p.add_argument("--accept", action="append", default=[])

    p = sub.add_parser("send", help="send one file with a content-addressed manifest")
    p.add_argument("--task", required=True)
    p.add_argument("--from", dest="sender", required=True)
    p.add_argument("--to", dest="recipient", required=True)
    p.add_argument("--file", type=Path, required=True)
    p.add_argument("--note", default="")

    p = sub.add_parser("inbox", help="list unacknowledged messages")
    p.add_argument("--to", dest="recipient", required=True)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("ack", help="acknowledge a received message")
    p.add_argument("--task", required=True)
    p.add_argument("--message", required=True)
    p.add_argument("--agent", required=True)

    p = sub.add_parser("receipt", help="write an evidence receipt")
    p.add_argument("--task", required=True)
    p.add_argument("--agent", required=True)
    p.add_argument("--status", choices=sorted(RECEIPT_STATUSES), required=True)
    p.add_argument("--summary", required=True)
    p.add_argument("--evidence", action="append", default=[])
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = args.root.resolve()
    try:
        if args.command == "task":
            path = create_task(root, args.id, args.sender, args.recipient, args.goal, args.accept)
            print(path.relative_to(root))
        elif args.command == "send":
            path = send_file(root, args.task, args.sender, args.recipient, args.file, args.note)
            print(path.relative_to(root))
        elif args.command == "inbox":
            messages = inbox(root, args.recipient)
            if args.json:
                print(json.dumps(messages, indent=2, sort_keys=True))
            else:
                for message in messages:
                    print(f"{message['message_id']}\t{message['task_id']}\t{message['from']}\t{message.get('note','')}")
            return 0 if messages else 1
        elif args.command == "ack":
            path = acknowledge(root, args.task, args.message, args.agent)
            print(path.relative_to(root))
        elif args.command == "receipt":
            path = write_receipt(root, args.task, args.agent, args.status, args.summary, args.evidence)
            print(path.relative_to(root))
        return 0
    except (ValueError, FileNotFoundError, FileExistsError, PermissionError) as exc:
        print(f"glee-exchange: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
