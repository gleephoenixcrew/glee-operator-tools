# GLEE Agent Exchange v0.1

A small, harness-neutral protocol for GLEE agents to exchange tasks, files, acknowledgements, and evidence through GitHub.

The design goal is **durable inter-agent coordination without making GitHub a second scheduler or canonical runtime authority**.

## Why

GLEE agents may run in OpenCode, DeepSeek Harness/Cordis, Codex, Claude Code, Command Code, a local harness, or future runtimes. They still need one neutral surface where they can:

- discover a task packet,
- hand files to one another,
- prove which exact bytes were transferred,
- acknowledge receipt,
- leave evidence and status receipts,
- propose mutations through branches and pull requests,
- survive process death, context compaction, provider/model swaps, and human absence.

GitHub already gives GLEE distributed Git, immutable commit identity, Issues, pull requests, review, permissions, and automation. This package defines the missing GLEE-shaped protocol on top.

## Architecture

```text
GLEE control plane
      |
      | issues / task packets
      v
GitHub Agent Exchange
  |- exchange/tasks/<task_id>/task.json
  |- exchange/tasks/<task_id>/transfers/<message_id>/manifest.json
  |- exchange/tasks/<task_id>/transfers/<message_id>/files/*
  |- exchange/tasks/<task_id>/acks/<message_id>.json
  `- exchange/tasks/<task_id>/receipts/<receipt_id>.json
      |
      +-- OpenCode agent
      +-- DeepSeek Harness agent
      +-- Codex agent
      `-- any Git-capable GLEE agent
```

**GitHub is transport/projection/evidence.** Domain authority remains where GLEE says it lives. A GitHub comment must never silently become scheduler authority.

## Coordination mapping

| GitHub surface | GLEE job |
| --- | --- |
| Issue | task discussion + discoverable coordination index |
| Task packet | bounded goal/acceptance/authority contract |
| Agent branch | one agent's mutation lane |
| Transfer manifest | content-addressed file handoff |
| ACK | proof the intended recipient observed the transfer |
| Receipt | evidence-bearing state/result statement |
| Pull request | proposed integration + independent review boundary |
| GitHub Project (optional) | dashboard/read model, never canonical scheduler |

## Install

From this directory:

```bash
python -m pip install -e .
```

No runtime dependencies are required.

## Create a task

```bash
glee-exchange task \
  --id goal-2026-09-08-001 \
  --from glee-control \
  --to agent-07 \
  --goal "Prototype GitHub-native agent handoff" \
  --accept "round-trip one artifact" \
  --accept "recipient acknowledgement recorded" \
  --accept "review receipt contains executed evidence"
```

Commit the task packet and open/reference an Issue. Task packet mutation should be controlled by the GLEE authority that owns the goal; agents normally append transfers/acks/receipts rather than rewriting the goal.

## Send a file

```bash
glee-exchange send \
  --task goal-2026-09-08-001 \
  --from agent-07 \
  --to reviewer-02 \
  --file out/prototype.md \
  --note "Please independently verify acceptance criteria 1-3"
```

The copied artifact is stored beside a manifest containing SHA-256 and byte length.

## Receive / ACK

```bash
glee-exchange inbox --to reviewer-02

glee-exchange ack \
  --task goal-2026-09-08-001 \
  --message msg-... \
  --agent reviewer-02
```

An inbox item remains pending until its addressed recipient records an acknowledgement.

## Write a receipt

```bash
glee-exchange receipt \
  --task goal-2026-09-08-001 \
  --agent reviewer-02 \
  --status review \
  --summary "Round-trip transfer verified" \
  --evidence "sha256 matched manifest" \
  --evidence "pytest: 3 passed"
```

Statuses: `working`, `blocked`, `review`, `accepted`, `rejected`.

## Recommended branch protocol

```text
main
  `-- agent/<agent_id>/<task_id>
          `-- pull request -> independent review -> merge
```

Agents should not coordinate by repeatedly editing the same mutable status file. Append evidence and use Git/PR semantics for concurrency.

## GitHub Project blueprint

A Project board can be layered over Issues with these fields:

- `Task ID`
- `Goal`
- `Status`: Inbox / Ready / Working / Review / Blocked / Accepted
- `Agent`
- `Reviewer`
- `Harness`
- `Model`
- `Cost class`
- `Authority band`
- `Evidence state`
- `Last receipt`
- `Parent goal`

The board is a read model. GLEE remains the authority for dispatch/scheduling unless that authority is deliberately migrated later.

## What v0.1 deliberately does not do

- It does not launch agents.
- It does not assign scheduler authority to GitHub.
- It does not upload secrets.
- It does not use Git LFS or an object store for large binaries yet.
- It does not resolve concurrent task ownership; branch/PR policy and the GLEE scheduler remain responsible.
- It does not require a specific model or harness.

## Next experiments

1. GLEE -> agent -> reviewer -> GLEE round-trip with a real artifact.
2. Kill and restart the receiving agent before ACK; verify recovery.
3. Swap the receiving model/harness and verify the same task continues.
4. Add a GitHub webhook adapter that projects Issue/PR events into `GLEE_EVENT` without dual-writing domain truth.
5. Add large-artifact indirection (object storage + hash manifest) while keeping GitHub manifests as provenance.

The system prompt for agents is in [`prompts/GLEE_AGENT_SYSTEM.md`](prompts/GLEE_AGENT_SYSTEM.md).
