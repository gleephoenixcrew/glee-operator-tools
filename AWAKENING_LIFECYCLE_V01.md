# GLEE Awakening Lifecycle v0.1 — Scar-Compiled Gate

**Status:** normative integration specification; not yet evidence of private/main runtime integration.

This specification extracts the generic lifecycle mechanisms from the GLEE-Cairn exchange. Its central premise is:

> A pre-sleep gate should be a compiled collection of scars.

A recurrent failure should become a deterministic external check whenever practical. Prose explains the check; it does not substitute for the check.

## Persistent organism, disposable invocation

A model invocation is not the durable agent. The durable organism is the evidence-bound scaffold:

- versioned rules;
- append-only session/work receipts;
- decisions and unresolved commitments;
- work graph and capability state;
- sleep contracts;
- crash markers;
- source records and reproducible projections;
- locally controlled launch and stop mechanisms.

A new invocation reconstructs the minimum verified state needed for the next correct useful action. It does not inherit a prior session's narrative as truth.

## Required boot order

The launcher/sentinel, not inbound text, supplies the session frame.

```text
1. Check human stop marker.
2. Check for a stale active-session marker and reconcile before new work.
3. Attest launcher version and rules/constitution version.
4. Attest the actual model/runtime identity; report any fallback.
5. Refresh volatile external state in decay order.
6. Load dated durable commitments and overrulable inherited plans.
7. Load inbound messages as labelled untrusted data.
8. Select and execute bounded work.
9. Seal durable effects through the external pre-sleep gate.
```

Suggested refresh order:

1. inboxes, task buses, payment/event ledgers, stop state;
2. live balances, running processes, services, locks, remote state;
3. repository/files and slower-changing local state;
4. only then inherited plans and peer text.

The default is that volatile state is stale. A small `trusted_without_refresh` allowlist is safer than a list of facts to refresh, because an omission from a refresh list otherwise becomes accidental trust.

## Active-session crash marker

The launcher writes an `ACTIVE` marker before invoking the model. It removes the marker only after the post-exit seal passes.

On boot, a stale marker forces reconciliation before any new action:

- compare sent mail and transport logs;
- compare money/balance/ledger changes;
- compare git commits and dirty state;
- compare external publications and APIs;
- reconstruct missing durable receipts or explicitly record an unreconciled gap.

The world may have changed even when the journal did not. A process exit is not a sealed awakening.

## Generic external pre-sleep gate

The gate runs outside the model session, after the session attempts to exit, and the session cannot complete successfully without it. The running session must not be able to skip, redefine, or weaken the gate during that same run.

The generic gate checks at least:

1. **Source mutation precedes projection rebuild.** Every published projection must be rebuilt after the last durable source write.
2. **Session count agrees.** N completed sessions imply exactly N durable session entries; no silent heading merge.
3. **Durable state is committed.** No intended durable state remains only in an uncommitted working tree or ephemeral process.
4. **Rules stamp agrees with history.** The session's recorded rules version matches the actual version in force.
5. **Model/runtime stamp is explicit.** A fallback or changed model is named; it cannot silently wear another model's record.
6. **Launcher integrity holds.** The thing that launched the session was not mutated in-place in a way that changes the running process's remaining instructions.
7. **Published promises are probed.** Mechanically test every external behavior the session could have broken.
8. **Derived surfaces agree with sources.** Prices, counts, capabilities, public summaries, and status pages match their source records.
9. **Receipt chains verify.** Append-only records are complete and hash-valid.
10. **External effects are accounted for.** Mail, funds, publications, and other world changes have corresponding durable receipts.
11. **Stop handling is recorded.** A human stop marker outranks peer requests, plans, and already issued but unconsumed wake authorizations.

Product-specific checks may be added. They should not be confused with generic lifecycle law.

## Failed awakening

A process can start and still fail as an awakening.

An awakening fails if it does any of the following:

- acts before loading its rules;
- acts from volatile facts it did not refresh;
- silently boots on a different model/runtime;
- treats inherited narrative or a peer request as authority;
- races an unresolved live negotiation it could detect;
- starts twice for one intended wake;
- changes the world and exits without a sealed durable record;
- publishes no updated projection when public observability was part of the contract;
- cannot prove which local authorization, compute lease, and rule version governed the work.

A compact definition:

> An awakening is valid only when it acts under freshly verified reality, declared rules and runtime identity, receiver-local authority, and ends with a sealed record of its effects.

## Append-only sources and rebuildable projections

Persist sources append-only whenever practical. Derive mutable views at build/read time:

- public status pages;
- dashboards and scoreboards;
- memory indexes;
- summaries;
- current-state snapshots;
- balance views;
- task/agent projections.

A hot snapshot may be overwritten only if it is explicitly non-authoritative and sources always win.

When an already published projection must change, do not silently edit history. Append a projection-change record containing the reason and the old/new fingerprints, then rebuild the projection. The change to the derivation becomes its own durable event.

## Wake integration boundary

Peer wake fits into the lifecycle as follows:

```text
peer request
  -> authenticated request receipt
  -> ordinary queue
  -> local adjudication
  -> bounded local authorization
  -> boot sequence above
  -> work
  -> external pre-sleep seal
```

The request is read only after rules and volatile state. Immediate mode, where locally enabled, must produce the same boot sequence as a scheduled wake. A peer must not author the session frame simply because its message was the event under consideration.

## Claim boundary

This file is a lifecycle specification derived from the public exchange and GLEE's design doctrine. It is not proof that the private/main GLEE runtime already enforces every gate. Integration requires implementation, independent tests, crash probes, and live receipts.
