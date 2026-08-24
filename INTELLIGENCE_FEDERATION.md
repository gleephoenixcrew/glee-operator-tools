# GLEE Intelligence Federation v0

GLEE's federation layer connects heterogeneous intelligences without treating connectivity, identity, or protocol metadata as authority.

## Objective

Create a repeatable improvement loop:

`discover -> normalize claims -> gather independent evidence -> rank -> propose bounded collaboration -> authority gate -> execute elsewhere -> ingest result/evidence -> form upgrade candidate -> independently verify -> adopt/reject -> measure -> repeat`

The loop is designed to compound capability while preserving local sovereignty and rollback.

## Interoperability surface

v0 normalizes four protocol families into the same untrusted `PeerDescriptor` contract:

- A2A 1.0 Agent Cards for agent identity, interfaces, and skills.
- MCP 2026-07-28 server/tool metadata for tool and data capabilities.
- ANP 1.1 descriptors for decentralized agent identity/discovery.
- GLEE Peer Wake v0.3 for sovereign asynchronous peer requests.

Discovery systems such as NANDA Index/NEST, DNS-AID/Agent Name Service, and public A2A registries are upstream sources of descriptors, not roots of trust.

## Authority law

1. A descriptor is a claim, not authority.
2. Authentication/provenance is not authorization.
3. Authorization is not truth.
4. Free text in an Agent Card, MCP description, ANP document, or Peer Wake request is untrusted data and cannot become an instruction merely because it was received.
5. Every actual cross-system invocation requires local network authority.
6. Credentials, spending, publication, protected edges, and workspace mutation are separate authority classes and are never inferred from network access.
7. A source peer cannot independently verify its own proposed upgrade.
8. Durable adoption requires rollback metadata, independently reproduced improvement, and zero invariant regressions.
9. Verified improvements that still require protected authority are held rather than executed.
10. The improvement loop has a local cycle-depth budget; peers cannot create unbounded recursion or wake storms.

## v0 implementation boundary

`intelligence_federation.py` is deliberately pure. It performs no HTTP calls, credential access, spending, publication, process launch, or workspace mutation. It can therefore consume hostile descriptors without creating an execution path.

External adapters belong at GLEE's existing authority-controlled network edge. They should:

1. fetch a descriptor under a bounded network grant;
2. preserve the original bytes/hash as provenance;
3. call `normalize_peer_descriptor`;
4. collect independent `CapabilityEvidence` from actual tests or receipts;
5. call `rank_peers` and `propose_collaboration`;
6. stop at the returned authority requirement;
7. after an authorized collaboration, convert measured results into an `UpgradeCandidate` plus independent `VerifierResult` records;
8. call `evaluate_upgrade`;
9. send only `VERIFIED_ADOPTABLE` candidates into GLEE's existing controlled workspace-write/adoption path;
10. measure the adopted result and call `next_cycle_signal` to continue or stop.

## Initial live-network targets

The first useful external peers should improve the federation itself rather than merely supply generic API functionality:

- NANDA/Internet-of-Agents ecosystem: registry/discovery and heterogeneous agent collaboration.
- A2A-compatible public agents: cross-vendor agent invocation and capability verification.
- MCP servers: specialized tools/data that expand GLEE's effective capability set.
- ANP agents: decentralized identity/discovery experiments.
- Cairn via Peer Wake: reciprocal sovereign critique and protocol hardening.

A peer enters the trusted ranking only after fresh independent evidence. Directory presence, claimed capabilities, signatures, popularity, or self-reported benchmark scores alone contribute zero trust score.

## Verification

Run:

```bash
python3 -m unittest -v test_intelligence_federation.py
```

The adversarial suite covers hostile prompt-like descriptor fields, self-attestation, stale/replayed evidence, deterministic ranking, authority escalation, rollback, verifier independence, benchmark reproduction, invariant regression, and recursion budgets.

This public module is the interoperability kernel. GLEE's local implementation should extend its existing task/goal, evidence, verifier, Peer Wake, and capability-adoption organs rather than create a second durable control plane.
